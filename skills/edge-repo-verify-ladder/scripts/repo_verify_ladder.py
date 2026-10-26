"""Verification ladder for a JS/TS repo received from someone else.

Runs the checks in the order that surfaced real defects on a first pass over a
fresh clone, and reports the traps that make a green run lie: code the
typechecker never sees, test runners broken by the host Node, generated clients
that were never generated, and a disk too full to finish a build.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           shell=(os.name == "nt"))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


def load_json(path: Path) -> dict:
    try:
        # tsconfig allows comments and trailing commas. Match strings first so
        # path globs like "@/*" are not mistaken for comment openers.
        text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/',
                      lambda m: m.group(1) or "", path.read_text(encoding="utf-8"), flags=re.S)
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
    except (OSError, ValueError):
        return {}


def node_major() -> int:
    node = shutil.which("node")
    out = node and subprocess.run([node, "-v"], capture_output=True, text=True).stdout
    m = re.match(r"v(\d+)", out or "")
    return int(m.group(1)) if m else 0


def ladder(repo: Path, run_tests: bool) -> list[dict]:
    findings: list[dict] = []

    def add(step: str, status: str, detail: str) -> None:
        findings.append({"step": step, "status": status, "detail": detail})

    if not (repo / "package.json").exists():
        add("package", "fail", "no package.json; not a JS/TS repo root")
        return findings
    pkg = load_json(repo / "package.json")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

    free_gb = shutil.disk_usage(repo).free / 1024 ** 3
    add("disk", "warn" if free_gb < 2 else "ok",
        f"{free_gb:.1f} GB free; builds copy node_modules into standalone output and "
        "editors truncate files on ENOSPC, so write edits atomically below ~2 GB")

    if not (repo / "node_modules").exists():
        add("install", "fail", "node_modules missing; run npm ci first")
        return findings

    if (repo / "prisma" / "schema.prisma").exists():
        client = repo / "node_modules" / ".prisma" / "client" / "index.js"
        add("prisma-client", "ok" if client.exists() else "fail",
            "generated" if client.exists() else
            "client not generated; every test importing @prisma/client fails until `npx prisma generate`")

    major = node_major()
    vitest_cfg = next((repo / n for n in ("vitest.config.ts", "vitest.config.mts", "vitest.config.js")
                       if (repo / n).exists()), None)
    cfg = vitest_cfg.read_text(encoding="utf-8", errors="replace") if vitest_cfg else ""
    if major >= 25 and "jsdom" in cfg:
        ok = "no-experimental-webstorage" in cfg
        add("node-webstorage", "ok" if ok else "fail",
            "handled" if ok else
            f"Node {major} ships a global localStorage that shadows jsdom's "
            "(`localStorage.clear is not a function`); set test.execArgv: "
            "['--no-experimental-webstorage'] (Vitest 4 dropped poolOptions.*.execArgv)")

    tsconfig = load_json(repo / "tsconfig.json")
    excluded = [e for e in tsconfig.get("exclude", []) if e != "node_modules"
                and (repo / e).is_dir() and any((repo / e).rglob("*.ts"))]
    for d in excluded:
        cfg = repo / f".tsconfig.ladder.{d.replace('/', '_')}.json"
        cfg.write_text(json.dumps({"extends": "./tsconfig.json", "include": [f"{d}/**/*.ts"],
                                   "exclude": ["node_modules"],
                                   "compilerOptions": {"noEmit": True, "incremental": False}}),
                       encoding="utf-8")
        try:
            _, out = run(["npx", "tsc", "-p", cfg.name], repo)
        finally:
            cfg.unlink(missing_ok=True)
        errs = [l for l in out.splitlines() if "error TS" in l]
        syntax = [l for l in errs if re.search(r"error TS1\d{3}", l)]
        add(f"typecheck:{d}", "fail" if errs else "ok",
            f"{len(errs)} errors in a dir tsconfig excludes (lint and tests never see it)"
            + (f"; {len(syntax)} are syntax errors, which hide semantic errors in the same file "
               "and often mean a botched splice: look for call arguments with no call head"
               if syntax else ""))

    code, out = run(["npx", "tsc", "--noEmit"], repo)
    n = out.count("error TS")
    add("typecheck:app", "fail" if n else "ok", f"{n} errors")

    if run_tests and "vitest" in deps:
        code, out = run(["npx", "vitest", "run", "--maxWorkers=4"], repo, timeout=1800)
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        summary = " | ".join(l.strip() for l in out.splitlines() if re.match(r"\s*(Test Files|Tests|Errors)\s", l))
        failed = sorted(set(re.findall(r"FAIL\s+(\S+\.(?:spec|test)\.\w+)", out)))
        add("tests", "fail" if code else "ok",
            summary + (f"; failing files: {', '.join(failed[:12])}" if failed else "")
            + ("; worker crashes under full parallelism are load, not code: keep the cap"
               if "Worker forks emitted error" in out else ""))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--no-tests", action="store_true", help="skip the test run")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()
    findings = ladder(Path(args.repo).resolve(), not args.no_tests)
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        for f in findings:
            print(f"[{f['status'].upper():4}] {f['step']}: {f['detail']}")
    return 1 if any(f["status"] == "fail" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
