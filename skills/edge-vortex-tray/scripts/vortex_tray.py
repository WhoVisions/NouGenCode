"""
NodeWorker Vortex tray controller.

Single source of truth for supervising the NodeWorker Node (look.py), Cortex
ingestion (Cortex.py), and the Vortex Dashboard from the Windows system tray.

Design notes
------------
Process state is resolved by ONE background sweep shared by every consumer
(menu labels, icon badge, guards). Menu callbacks never touch psutil, so
opening the tray menu is instant regardless of how many processes the host
is running.

Every mutating action is serialised through a reentrant lock, so a restart
is atomic: nothing can slip a start in between the kill and the respawn.

"Flush VRAM" issues a real Ollama unload (keep_alive=0 against every
resident model) rather than writing an advisory file. The breadcrumb file is
still written for any external watcher, but it is not the mechanism.

Configuration is entirely environment-driven; see CONFIG below.
"""

from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray
from pystray import Menu, MenuItem as item

try:
    import psutil

    HAVE_PSUTIL = True
except ImportError:  # pragma: no cover - degraded mode
    psutil = None  # type: ignore[assignment]
    HAVE_PSUTIL = False


APP_NAME = "NodeWorker Vortex"
MUTEX_NAME = "Global\\IRISVortexTraySingleton"
ERROR_ALREADY_EXISTS = 183


# -----------------------------
# Configuration
# -----------------------------


def _env_path(key: str, default: Path | str) -> Path:
    return Path(os.getenv(key, str(default)))


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_flag(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


OUTPOST_DIR = _env_path("VORTEX_OUTPOST_DIR", r"./data")
PERSISTENCE_DIR = OUTPOST_DIR / "persistence"

LOOK_SCRIPT = _env_path("VORTEX_LOOK_SCRIPT", PERSISTENCE_DIR / "look.py")
CORTEX_SCRIPT = _env_path("VORTEX_CORTEX_SCRIPT", PERSISTENCE_DIR / "Cortex.py")
DASHBOARD_SCRIPT = _env_path("VORTEX_DASHBOARD_SCRIPT", OUTPOST_DIR / "vortex_dashboard.py")
BLACKBOX_LOG = _env_path("VORTEX_BLACKBOX_LOG", PERSISTENCE_DIR / "iris_blackbox.jsonl")
FLUSH_SIGNAL = _env_path("VORTEX_FLUSH_SIGNAL", PERSISTENCE_DIR / "vram_flush.signal")
TRAY_LOG = _env_path("VORTEX_TRAY_LOG", PERSISTENCE_DIR / "vortex_tray.log")

ICON_PATH = _env_path(
    "VORTEX_ICON_PATH",
    r"./data"
    r"\1fa6482c-2a88-48f7-9870-7899e25621c8\iris_vortex_icon_png_1776404646186.png",
)

PYTHON_CONSOLE = _env_path("VORTEX_PYTHON", sys.executable)


def _default_pythonw() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


PYTHON_WINDOWED = _env_path("VORTEX_PYTHONW", _default_pythonw())

OLLAMA_HOST = os.getenv("VORTEX_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_TIMEOUT = _env_float("VORTEX_OLLAMA_TIMEOUT", 10.0)

INTERPRETER_NAMES = tuple(
    os.getenv("VORTEX_INTERPRETER_NAMES", "python.exe,pythonw.exe,python3.exe,python").split(",")
)

POLL_INTERVAL = _env_float("VORTEX_POLL_INTERVAL", 3.0)
START_VERIFY_WINDOW = _env_float("VORTEX_START_VERIFY_WINDOW", 1.5)
TERMINATE_TIMEOUT = _env_float("VORTEX_TERMINATE_TIMEOUT", 5.0)
RESTART_GAP = _env_float("VORTEX_RESTART_GAP", 0.7)

LOG_MAX_BYTES = int(_env_float("VORTEX_LOG_MAX_BYTES", 2_000_000))
LOG_BACKUPS = int(_env_float("VORTEX_LOG_BACKUPS", 3))
ALLOW_MULTIPLE = _env_flag("VORTEX_ALLOW_MULTIPLE_TRAYS", False)

CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
WINDOWS_CREATION_FLAGS = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS


# -----------------------------
# Logging
# -----------------------------

log = logging.getLogger("vortex.tray")


def configure_logging() -> None:
    """Attach a rotating file handler to our own logger.

    A dedicated logger is used rather than logging.basicConfig() because
    basicConfig is a silent no-op once any other import has configured the
    root logger, which historically caused tray events to vanish.
    """
    log.setLevel(logging.INFO)
    log.propagate = False
    if log.handlers:
        return

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] pid=%(process)d %(message)s"
    )

    try:
        TRAY_LOG.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            TRAY_LOG,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(fmt)
    log.addHandler(handler)


configure_logging()


# -----------------------------
# Process model
# -----------------------------


@dataclass(frozen=True)
class ManagedProcess:
    """A live process matched to one of the scripts we supervise."""

    pid: int
    create_time: float
    is_dupe: bool
    role: Optional[str]

    @property
    def uptime(self) -> float:
        return max(0.0, time.time() - self.create_time)


@dataclass
class ScriptSpec:
    """A supervised script and how to identify its processes."""

    key: str
    label: str
    path: Path
    python: Path
    windowless: bool = False
    dupe_role: Optional[str] = None
    exclude_prefixes: tuple[str, ...] = ()
    singleton: bool = True

    @property
    def script_name(self) -> str:
        return self.path.name


@dataclass
class Snapshot:
    """Result of one process sweep."""

    by_key: dict[str, list[ManagedProcess]] = field(default_factory=dict)
    taken_at: float = 0.0
    degraded: bool = False

    def running(self, key: str) -> list[ManagedProcess]:
        return self.by_key.get(key, [])

    def is_running(self, key: str) -> bool:
        return bool(self.by_key.get(key))

    def dupes(self, key: str) -> list[ManagedProcess]:
        return [p for p in self.by_key.get(key, []) if p.is_dupe]

    def signature(self) -> tuple:
        return tuple(
            (key, tuple(sorted(p.pid for p in procs)))
            for key, procs in sorted(self.by_key.items())
        )


class ProcessRegistry:
    """Resolves every supervised script in a single psutil sweep.

    The expensive part of identifying a duplicate instance is reading a
    process environment block, so that is only done for the handful of
    processes that already matched a supervised script — never for the
    full process table.
    """

    def __init__(self, specs: dict[str, ScriptSpec]) -> None:
        self._specs = specs
        self._by_name: dict[str, list[ScriptSpec]] = {}
        for spec in specs.values():
            self._by_name.setdefault(spec.script_name.lower(), []).append(spec)

        names = {spec.python.name.lower() for spec in specs.values()}
        names.update(n.strip().lower() for n in INTERPRETER_NAMES if n.strip())
        self._interpreter_names = names

    def _is_interpreter(self, name: str) -> bool:
        return "python" in name or name in self._interpreter_names

    def _iter_candidates(self):
        """Yield (proc, cmdline) for interpreter processes only.

        Reading a command line is by far the most expensive per-process call
        on Windows, so it is deferred until the cheap process name says the
        process could plausibly be one of ours. On a host with a few hundred
        processes this turns a multi-second sweep into a few milliseconds.
        """
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except Exception:
                continue
            if not self._is_interpreter(name):
                continue
            try:
                cmdline = proc.cmdline()
            except Exception:
                continue
            if cmdline:
                yield proc, cmdline

    def sweep(self) -> Snapshot:
        snapshot = Snapshot(taken_at=time.time())
        snapshot.by_key = {key: [] for key in self._specs}

        if not HAVE_PSUTIL:
            snapshot.degraded = True
            return snapshot

        for proc, cmdline in self._iter_candidates():
            matched = self._match(cmdline)
            if not matched:
                continue

            env = self._read_env(proc)
            is_dupe = env.get("VORTEX_IS_DUPE") == "1"
            role = env.get("VORTEX_INSTANCE_ROLE") if is_dupe else None

            info = ManagedProcess(
                pid=proc.info.get("pid", -1),
                create_time=proc.info.get("create_time") or 0.0,
                is_dupe=is_dupe,
                role=role,
            )
            for spec in matched:
                snapshot.by_key[spec.key].append(info)

        return snapshot

    def _match(self, cmdline: list) -> list[ScriptSpec]:
        """Match a command line to supervised scripts by argument basename.

        Prefix exclusions are applied to the matched argument's basename
        only. Matching on the whole joined command line, as an earlier
        revision did, wrongly excluded any script living under a directory
        whose name happened to contain the prefix.
        """
        hits: list[ScriptSpec] = []
        for part in cmdline:
            try:
                basename = Path(str(part)).name.lower()
            except Exception:
                continue
            for spec in self._by_name.get(basename, ()):
                if spec.exclude_prefixes and basename.startswith(
                    tuple(p.lower() for p in spec.exclude_prefixes)
                ):
                    continue
                hits.append(spec)
        return hits

    @staticmethod
    def _read_env(proc) -> dict[str, str]:
        try:
            return proc.environ() or {}
        except Exception:
            # AccessDenied is normal for processes we do not own.
            return {}

    def processes_for(self, key: str, dupe_only: bool = False) -> list:
        """Return live psutil.Process handles for a supervised script."""
        if not HAVE_PSUTIL:
            return []

        spec = self._specs[key]
        out = []
        for proc, cmdline in self._iter_candidates():
            if spec not in self._match(cmdline):
                continue
            if dupe_only:
                env = self._read_env(proc)
                if env.get("VORTEX_IS_DUPE") != "1":
                    continue
                if spec.dupe_role and env.get("VORTEX_INSTANCE_ROLE") != spec.dupe_role:
                    continue
            out.append(proc)
        return out


# -----------------------------
# Ollama VRAM control
# -----------------------------


# The client lives in vortex_ollama so the dashboard shares exactly this
# implementation rather than keeping its own divergent copy. The sys.path
# insert makes the import work when this file is loaded by absolute path
# (tests, shims, embedded launchers) and not just via `python vortex_tray.py`.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from vortex_ollama import OllamaClient  # noqa: E402


# -----------------------------
# Tray app
# -----------------------------


class VortexTrayApp:
    def __init__(self) -> None:
        self.icon: Optional[pystray.Icon] = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._children: list[subprocess.Popen] = []
        self._base_icon: Optional[Image.Image] = None
        self._icon_state: Optional[tuple] = None
        self._ollama = OllamaClient()

        self.specs: dict[str, ScriptSpec] = {
            "NodeWorker": ScriptSpec(
                key="NodeWorker",
                label="NodeWorker Node",
                path=LOOK_SCRIPT,
                python=PYTHON_CONSOLE,
                dupe_role="NodeWorker",
            ),
            "cortex": ScriptSpec(
                key="cortex",
                label="Cortex Ingestion",
                path=CORTEX_SCRIPT,
                python=PYTHON_CONSOLE,
                dupe_role="CORTEX",
                exclude_prefixes=("test_",),
            ),
            "dashboard": ScriptSpec(
                key="dashboard",
                label="Vortex Dashboard",
                path=DASHBOARD_SCRIPT,
                python=PYTHON_WINDOWED,
                windowless=True,
            ),
        }

        self.registry = ProcessRegistry(self.specs)
        self._snapshot = Snapshot(taken_at=0.0, by_key={k: [] for k in self.specs})

    # ---------- state ----------

    @property
    def snapshot(self) -> Snapshot:
        return self._snapshot

    def refresh_snapshot(self) -> Snapshot:
        snap = self.registry.sweep()
        self._snapshot = snap
        return snap

    def _poll_loop(self) -> None:
        """Keep the shared snapshot warm so menu rendering never blocks."""
        last_sig: Optional[tuple] = None
        while not self._stop.wait(POLL_INTERVAL):
            try:
                snap = self.refresh_snapshot()
                self._reap_children()
                sig = snap.signature()
                if sig != last_sig:
                    last_sig = sig
                    self._apply_icon_state(snap)
                    self.refresh_menu()
            except Exception:
                log.exception("Status poll failed")

    def _reap_children(self) -> None:
        """Release handles for children that have already exited."""
        with self._lock:
            alive = []
            for child in self._children:
                if child.poll() is None:
                    alive.append(child)
            self._children = alive

    # ---------- UI helpers ----------

    def notify(self, message: str, title: str = APP_NAME, level: int = logging.INFO) -> None:
        log.log(level, "%s", message)
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception as exc:
                log.warning("Tray notification failed: %s", exc)

    def refresh_menu(self) -> None:
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception as exc:
                log.debug("Menu refresh failed: %s", exc)

    def run_async(self, fn: Callable, *args, **kwargs) -> None:
        def wrapped() -> None:
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                log.exception("Action failed: %s", getattr(fn, "__name__", fn))
                self.notify(f"Action failed: {exc}", level=logging.ERROR)

        threading.Thread(target=wrapped, daemon=True).start()

    # ---------- icon ----------

    def _load_base_icon(self) -> Image.Image:
        if self._base_icon is not None:
            return self._base_icon

        try:
            image = Image.open(ICON_PATH).convert("RGBA")
            image.thumbnail((64, 64))
            canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            canvas.paste(
                image,
                ((64 - image.width) // 2, (64 - image.height) // 2),
                image,
            )
        except Exception as exc:
            log.warning("Icon load failed at %s: %s", ICON_PATH, exc)
            canvas = Image.new("RGBA", (64, 64), (20, 20, 20, 255))
            draw = ImageDraw.Draw(canvas)
            draw.ellipse((8, 8, 56, 56), fill=(0, 220, 120, 255))
            draw.ellipse((20, 20, 44, 44), fill=(20, 20, 20, 255))

        self._base_icon = canvas
        return canvas

    def _badged_icon(self, iris_up: bool, cortex_up: bool) -> Image.Image:
        """Overlay a health badge so tray state is readable without a click."""
        image = self._load_base_icon().copy()
        draw = ImageDraw.Draw(image)

        if iris_up and cortex_up:
            colour = (0, 220, 120, 255)      # both up
        elif iris_up or cortex_up:
            colour = (245, 190, 40, 255)     # partial
        else:
            colour = (150, 150, 155, 255)    # idle

        draw.ellipse((42, 42, 62, 62), fill=(15, 15, 18, 255))
        draw.ellipse((45, 45, 59, 59), fill=colour)
        return image

    def _apply_icon_state(self, snap: Snapshot) -> None:
        if not self.icon:
            return
        state = (snap.is_running("NodeWorker"), snap.is_running("cortex"))
        if state == self._icon_state:
            return
        try:
            self.icon.icon = self._badged_icon(*state)
            self._icon_state = state
        except Exception as exc:
            log.debug("Icon badge update failed: %s", exc)

    # ---------- duplicate identity ----------

    @staticmethod
    def _dupe_env(role: str) -> dict[str, str]:
        """Give a duplicate instance a readable identity.

        Child scripts can branch on these to keep separate memory, logs,
        sockets or GPU behaviour:

            VORTEX_IS_DUPE / VORTEX_INSTANCE_ROLE / VORTEX_INSTANCE_ID
            IRIS_DUPE or CORTEX_DUPE

        Environment rather than argv, so scripts using argparse do not break.
        """
        role_clean = role.strip().upper().replace(" ", "_")
        instance_id = f"{role_clean.lower()}-dupe-{int(time.time() * 1000)}-{os.getpid()}"
        return {
            "VORTEX_IS_DUPE": "1",
            "VORTEX_INSTANCE_ROLE": role_clean,
            "VORTEX_INSTANCE_ID": instance_id,
            f"{role_clean}_DUPE": "1",
        }

    # ---------- lifecycle primitives ----------

    def _start(self, key: str, env_updates: Optional[dict[str, str]] = None) -> bool:
        """Spawn a supervised script and verify it survived startup."""
        spec = self.specs[key]
        with self._lock:
            if not spec.path.exists():
                self.notify(f"{spec.label} script not found: {spec.path}", level=logging.ERROR)
                return False
            if not spec.python.exists():
                self.notify(f"Python executable not found: {spec.python}", level=logging.ERROR)
                return False

            env = os.environ.copy()
            if env_updates:
                env.update(env_updates)

            stream = subprocess.DEVNULL if spec.windowless else None
            try:
                child = subprocess.Popen(
                    [str(spec.python), str(spec.path)],
                    cwd=str(spec.path.parent),
                    stdout=stream,
                    stderr=stream,
                    creationflags=WINDOWS_CREATION_FLAGS if os.name == "nt" else 0,
                    env=env,
                )
            except OSError as exc:
                log.exception("Spawn failed for %s", spec.label)
                self.notify(f"{spec.label} failed to start: {exc}", level=logging.ERROR)
                return False

            self._children.append(child)

            # Verify the process actually stayed up rather than reporting
            # success for something that exited immediately on an import error.
            deadline = time.time() + START_VERIFY_WINDOW
            while time.time() < deadline:
                code = child.poll()
                if code is not None:
                    self.notify(
                        f"{spec.label} exited immediately (code {code}). "
                        f"Run it in a console to see the traceback.",
                        level=logging.ERROR,
                    )
                    return False
                time.sleep(0.1)

            instance_id = env.get("VORTEX_INSTANCE_ID")
            suffix = f" as {instance_id}" if instance_id else ""
            self.notify(f"{spec.label} started{suffix} (pid {child.pid}).")

        self.refresh_snapshot()
        self._apply_icon_state(self._snapshot)
        self.refresh_menu()
        return True

    def _terminate(self, key: str, dupe_only: bool = False) -> int:
        spec = self.specs[key]
        with self._lock:
            if not HAVE_PSUTIL:
                self.notify(
                    "Install psutil to enable process status and kill controls.",
                    level=logging.WARNING,
                )
                return 0

            processes = self.registry.processes_for(key, dupe_only=dupe_only)
            scope = "duplicate " if dupe_only else ""
            if not processes:
                self.notify(f"No {scope}{spec.label} process is currently running.")
                self.refresh_menu()
                return 0

            for proc in processes:
                try:
                    proc.terminate()
                except Exception as exc:
                    log.warning(
                        "Could not terminate %s pid=%s: %s",
                        spec.label,
                        getattr(proc, "pid", "?"),
                        exc,
                    )

            killed = 0
            try:
                gone, alive = psutil.wait_procs(processes, timeout=TERMINATE_TIMEOUT)
                killed = len(gone)
                for proc in alive:
                    try:
                        proc.kill()
                        killed += 1
                    except Exception as exc:
                        log.warning(
                            "Could not kill %s pid=%s: %s",
                            spec.label,
                            getattr(proc, "pid", "?"),
                            exc,
                        )
            except Exception as exc:
                log.debug("wait_procs failed: %s", exc)
                killed = len(processes)

            self.notify(
                f"{scope}{spec.label} terminated "
                f"({killed} process{'es' if killed != 1 else ''})."
            )

        self.refresh_snapshot()
        self._apply_icon_state(self._snapshot)
        self.refresh_menu()
        return killed

    def _restart(self, key: str) -> None:
        """Kill then respawn without releasing the lock in between."""
        with self._lock:
            self._terminate(key)
            time.sleep(RESTART_GAP)
            self._start(key)

    def _open_path(self, path: Path, label: str) -> None:
        if not path.exists():
            self.notify(f"{label} not found: {path}", level=logging.WARNING)
            return
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            log.exception("Failed to open %s", path)
            self.notify(f"Could not open {label}: {exc}", level=logging.ERROR)

    def _guarded_start(self, key: str) -> None:
        """Start a singleton script, refusing to stack a second copy."""
        spec = self.specs[key]
        self.refresh_snapshot()
        if self._snapshot.is_running(key):
            pids = ", ".join(str(p.pid) for p in self._snapshot.running(key))
            hint = (
                f" Use Run {spec.label} Dupe if you intentionally want another copy."
                if spec.dupe_role
                else ""
            )
            self.notify(f"{spec.label} is already running (pid {pids}).{hint}")
            self.refresh_menu()
            return
        self._start(key)

    # ---------- tray actions ----------

    def open_outpost(self, icon=None, menu_item=None) -> None:
        self.run_async(self._open_path, OUTPOST_DIR, "Outpost home")

    def open_persistence(self, icon=None, menu_item=None) -> None:
        self.run_async(self._open_path, PERSISTENCE_DIR, "Persistence folder")

    def view_logs(self, icon=None, menu_item=None) -> None:
        self.run_async(self._open_path, BLACKBOX_LOG, "Blackbox logs")

    def view_tray_log(self, icon=None, menu_item=None) -> None:
        self.run_async(self._open_path, TRAY_LOG, "Tray log")

    def open_vortex_dashboard(self, icon=None, menu_item=None) -> None:
        self.run_async(self._guarded_start, "dashboard")

    def start_iris(self, icon=None, menu_item=None) -> None:
        self.run_async(self._guarded_start, "NodeWorker")

    def run_iris_dupe(self, icon=None, menu_item=None) -> None:
        self.run_async(self._start, "NodeWorker", self._dupe_env("NodeWorker"))

    def restart_iris(self, icon=None, menu_item=None) -> None:
        self.run_async(self._restart, "NodeWorker")

    def kill_iris(self, icon=None, menu_item=None) -> None:
        self.run_async(self._terminate, "NodeWorker")

    def kill_iris_dupes(self, icon=None, menu_item=None) -> None:
        self.run_async(self._terminate, "NodeWorker", True)

    def start_cortex(self, icon=None, menu_item=None) -> None:
        self.run_async(self._guarded_start, "cortex")

    def run_cortex_dupe(self, icon=None, menu_item=None) -> None:
        self.run_async(self._start, "cortex", self._dupe_env("CORTEX"))

    def restart_cortex(self, icon=None, menu_item=None) -> None:
        self.run_async(self._restart, "cortex")

    def kill_cortex(self, icon=None, menu_item=None) -> None:
        self.run_async(self._terminate, "cortex")

    def kill_cortex_dupes(self, icon=None, menu_item=None) -> None:
        self.run_async(self._terminate, "cortex", True)

    def kill_dashboard(self, icon=None, menu_item=None) -> None:
        self.run_async(self._terminate, "dashboard")

    def flush_vram(self, icon=None, menu_item=None) -> None:
        self.run_async(self._flush_vram)

    def _flush_vram(self) -> None:
        """Evict every resident Ollama model, and report what really happened."""
        result = self._ollama.flush_vram()
        self._write_flush_breadcrumb()
        level = logging.INFO if result.ok else logging.WARNING
        if result.error:
            level = logging.ERROR
        self.notify(result.summary(), level=level)

    @staticmethod
    def _write_flush_breadcrumb() -> None:
        """Advisory marker for external watchers. Not the flush mechanism."""
        try:
            FLUSH_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
            FLUSH_SIGNAL.write_text(str(time.time()), encoding="utf-8")
        except OSError as exc:
            log.debug("Flush breadcrumb write failed: %s", exc)

    def on_quit(self, icon, menu_item) -> None:
        log.info("Exiting Vortex tray (user requested).")
        self._stop.set()
        icon.stop()

    # ---------- dynamic labels ----------

    @staticmethod
    def _noop(icon=None, menu_item=None) -> None:
        return None

    def _status_label(self, key: str, name: str) -> str:
        snap = self._snapshot
        if snap.degraded:
            return f"⚪ {name}: unknown (psutil missing)"
        procs = snap.running(key)
        if not procs:
            return f"🔴 {name}: Offline"
        dupes = sum(1 for p in procs if p.is_dupe)
        extra = f" +{dupes} dupe{'s' if dupes != 1 else ''}" if dupes else ""
        mins = int(max(p.uptime for p in procs) // 60)
        return f"🟢 {name}: Running{extra} · {mins}m"

    def _iris_status(self, menu_item=None) -> str:
        return self._status_label("NodeWorker", "NodeWorker Node")

    def _cortex_status(self, menu_item=None) -> str:
        return self._status_label("cortex", "Cortex")

    def _dashboard_status(self, menu_item=None) -> str:
        return self._status_label("dashboard", "Dashboard")

    # ---------- main loop ----------

    def build_menu(self) -> Menu:
        return Menu(
            item("Open Vortex Dashboard", self.open_vortex_dashboard, default=True),
            item(self._dashboard_status, self._noop, enabled=False),
            item("Close Dashboard", self.kill_dashboard),
            Menu.SEPARATOR,
            item(self._iris_status, self._noop, enabled=False),
            item("Start NodeWorker Node", self.start_iris),
            item("Run NodeWorker Dupe", self.run_iris_dupe),
            item("Restart NodeWorker Node", self.restart_iris),
            item("Kill NodeWorker Node", self.kill_iris),
            item("Kill NodeWorker Dupes Only", self.kill_iris_dupes),
            Menu.SEPARATOR,
            item(self._cortex_status, self._noop, enabled=False),
            item("Start Cortex Background", self.start_cortex),
            item("Run Cortex Dupe", self.run_cortex_dupe),
            item("Restart Cortex Background", self.restart_cortex),
            item("Kill Cortex Background", self.kill_cortex),
            item("Kill Cortex Dupes Only", self.kill_cortex_dupes),
            Menu.SEPARATOR,
            item("Flush VRAM (Ollama unload)", self.flush_vram),
            Menu.SEPARATOR,
            item("View Blackbox Logs", self.view_logs),
            item("View Tray Log", self.view_tray_log),
            item("Open Persistence Folder", self.open_persistence),
            item("Open Outpost Home", self.open_outpost),
            item("Exit Vortex", self.on_quit),
        )

    def run(self) -> None:
        if not HAVE_PSUTIL:
            log.warning("psutil is not installed — status and kill controls are disabled.")

        self.refresh_snapshot()

        self.icon = pystray.Icon(
            "Vortex",
            self._badged_icon(
                self._snapshot.is_running("NodeWorker"),
                self._snapshot.is_running("cortex"),
            ),
            APP_NAME,
            self.build_menu(),
        )
        self._icon_state = (
            self._snapshot.is_running("NodeWorker"),
            self._snapshot.is_running("cortex"),
        )

        threading.Thread(target=self._poll_loop, name="vortex-poll", daemon=True).start()

        log.info(
            "Starting Vortex tray. python=%s outpost=%s ollama=%s",
            sys.version.split()[0],
            OUTPOST_DIR,
            OLLAMA_HOST,
        )
        self.icon.run()

    def shutdown(self, reason: str) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        log.info("Vortex tray stopped (%s).", reason)


# -----------------------------
# Single-instance guard
# -----------------------------


class SingleInstance:
    """Windows named mutex, with a lock-file fallback elsewhere."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle = None
        self._lockfile: Optional[Path] = None

    def acquire(self) -> bool:
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            self._handle = kernel32.CreateMutexW(None, False, self.name)
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                return False
            return bool(self._handle)

        self._lockfile = PERSISTENCE_DIR / "vortex_tray.lock"
        try:
            self._lockfile.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        if os.name == "nt" and self._handle:
            try:
                ctypes.windll.kernel32.CloseHandle(self._handle)  # type: ignore[attr-defined]
            except Exception:
                pass
        elif self._lockfile and self._lockfile.exists():
            try:
                self._lockfile.unlink()
            except OSError:
                pass


def main() -> int:
    guard = SingleInstance()
    if not ALLOW_MULTIPLE and not guard.acquire():
        log.warning(
            "Another Vortex tray is already running — refusing to start a second. "
            "Set VORTEX_ALLOW_MULTIPLE_TRAYS=1 to override."
        )
        return 1

    atexit.register(guard.release)
    app = VortexTrayApp()
    atexit.register(app.shutdown, "process exit")

    def _on_signal(signum, _frame):
        app.shutdown(f"signal {signum}")
        if app.icon:
            try:
                app.icon.stop()
            except Exception:
                pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    def _excepthook(exc_type, exc, tb):
        log.critical("Unhandled exception — tray is going down", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    try:
        app.run()
    finally:
        app.shutdown("run loop ended")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
