"""Report-only cleanup pass: measure every Python file, score it with ``scoring``, rank, propose.

Signals are deterministic (AST + git history); nothing is written to the repository. The pass is
the first execution step of a NouGenCode mission (see ``controller.execute_mission``), so feature
work starts from a ranked view of what to delete, merge, parameterize or repair.
"""
from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import scoring as S

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".tox", ".mypy_cache"}
BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith,
                ast.BoolOp, ast.IfExp, ast.ExceptHandler, ast.comprehension, ast.Assert)
EXPOSURE_MODS = {"socket", "http", "urllib", "requests", "httpx", "aiohttp", "fastapi", "flask", "argparse", "websockets"}
PRIV_CALLS = {"subprocess", "os.system", "os.popen", "ctypes", "eval", "exec", "pickle", "marshal", "shlex"}
MUT_CALLS = {"open", "os.remove", "os.unlink", "shutil.rmtree", "shutil.move", "os.rename", "write_text",
             "write_bytes", "unlink", "rmtree", "execute", "executemany", "commit"}
UNSRC_CALLS = {"os.environ", "os.getenv", "sys.argv", "input", "json.loads", "yaml.safe_load", "recv", "read"}
NONDET = {"random", "time.time", "datetime.now", "uuid.uuid4"}
DEFECT_PATTERNS = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
SIM_THRESHOLD_FOR_PAIRS = 0.6
MAX_FUNCS_COMPARED = 4000


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


@dataclass
class FuncSig:
    file: str
    name: str
    shingles: Set[str]
    idents: Set[str]
    arity: int
    returns: bool
    globals_used: Set[str]
    loc: int


@dataclass
class FileFacts:
    path: Path
    rel: str
    module: str
    is_test: bool
    loc: int = 0
    cc: int = 1
    imports: Set[str] = field(default_factory=set)
    defined: Set[str] = field(default_factory=set)
    public: Set[str] = field(default_factory=set)
    exported: Set[str] = field(default_factory=set)
    used_names: Set[str] = field(default_factory=set)
    strings: Set[str] = field(default_factory=set)
    state: int = 0
    calls: Set[str] = field(default_factory=set)
    defects: int = 0
    is_entry: bool = False
    syntax_error: bool = False
    funcs: List[FuncSig] = field(default_factory=list)


def _shingles(node: ast.AST) -> Set[str]:
    kinds = [type(n).__name__ for n in ast.walk(node)]
    return {"/".join(kinds[i:i + 3]) for i in range(max(len(kinds) - 2, 1))}


def _module_name(rel: str) -> str:
    parts = Path(rel).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect(root: Path) -> List[FileFacts]:
    out: List[FileFacts] = []
    for path in sorted(root.rglob("*.py")):
        if any(p in SKIP_DIRS or p.startswith(".") for p in path.relative_to(root).parts[:-1]):
            continue
        rel = path.relative_to(root).as_posix()
        name = path.name
        f = FileFacts(path=path, rel=rel, module=_module_name(rel),
                      is_test=name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel}" or name == "conftest.py")
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        f.loc = sum(1 for line in src.splitlines() if line.strip() and not line.strip().startswith("#"))
        f.defects = len(DEFECT_PATTERNS.findall(src))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            f.syntax_error = True
            out.append(f)
            continue
        _visit(f, tree)
        out.append(f)
    return out


def _visit(f: FileFacts, tree: ast.Module) -> None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            f.defined.add(node.name)
            if not node.name.startswith("_"):
                f.public.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    if t.id == "__all__" and isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
                        f.exported |= {e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                    elif not t.id.isupper():
                        f.state += 1
        elif isinstance(node, ast.If) and _dotted(getattr(node.test, "left", node.test)) == "__name__":
            f.is_entry = True
    for node in ast.walk(tree):
        if isinstance(node, BRANCH_NODES):
            f.cc += 1
        if isinstance(node, ast.Import):
            f.imports |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = "." * node.level + base
            f.imports.add(base)
            f.used_names |= {a.name for a in node.names}
        elif isinstance(node, ast.Name):
            f.used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            f.used_names.add(node.attr)
            f.used_names.add(_dotted(node))  # e.g. os.environ, for trust-boundary sources
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
            f.strings.add(node.value)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            f.state += len(node.names)
        elif isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})):
            if all(isinstance(b, ast.Pass) for b in node.body):
                f.defects += 1
        elif isinstance(node, ast.Call):
            f.calls.add(_dotted(node.func))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(node.body) >= 3:
            idents = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            f.funcs.append(FuncSig(
                file=f.rel, name=node.name, shingles=_shingles(node), idents=idents,
                arity=len(node.args.args) + len(node.args.kwonlyargs),
                returns=any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node)),
                globals_used={n for g in ast.walk(node) if isinstance(g, ast.Global) for n in g.names},
                loc=(getattr(node, "end_lineno", node.lineno) - node.lineno + 1),
            ))
            for d in node.args.defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    f.defects += 1


def _jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _git_ages(root: Path) -> Tuple[Dict[str, float], Dict[str, int]]:
    """Days since last change and commit count in the last 90 days, per repo-relative path."""
    age: Dict[str, float] = {}
    churn: Dict[str, int] = {}
    try:
        log = subprocess.run(["git", "-C", str(root), "log", "--since=365.days", "--name-only", "--format=@%ct"],
                             capture_output=True, text=True, timeout=60, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return age, churn
    now, ts = time.time(), None
    for line in log.splitlines():
        if line.startswith("@"):
            ts = int(line[1:])
        elif line.strip() and ts:
            days = (now - ts) / 86400
            age.setdefault(line.strip(), days)
            if days <= 90:
                churn[line.strip()] = churn.get(line.strip(), 0) + 1
    return age, churn


def _level(hits: int) -> float:
    return 0.0 if hits <= 0 else (0.5 if hits == 1 else 1.0)


def _matches(calls: Iterable[str], names: Set[str]) -> int:
    return sum(1 for c in calls if c in names or c.split(".")[0] in names or c.split(".")[-1] in names)


@dataclass
class FileScore:
    file: str
    module: str
    metrics: Dict[str, int]
    signals: Dict[str, float]
    ID: float
    RP: float
    RED: float
    RED_peer: Optional[str]
    DV: float
    MV: float
    PV: float
    Pdead: float
    TBR: float
    action: str
    action_value: float
    requires_review: bool
    blocked: List[str]
    expected_SG: float
    capability_delta: float
    delta_ID: float
    test_obligations: List[str]


def run_cleanup_pass(root: str | Path, *, weights: Optional[Dict[str, float]] = None,
                     include_tests: bool = False, top: Optional[int] = None) -> Dict[str, object]:
    root = Path(root).resolve()
    w = weights or S.load_weights()
    facts = collect(root)
    tests = [f for f in facts if f.is_test]
    age, churn = _git_ages(root)
    entry_strings: Set[str] = set()
    for cfg in ("pyproject.toml", "setup.cfg", "setup.py"):
        p = root / cfg
        if p.exists():
            entry_strings |= set(re.findall(r"[\w.]+", p.read_text(encoding="utf-8", errors="replace")))

    # Fan-in: which modules import this one (absolute or by trailing segment for relative imports).
    fan_in: Dict[str, Set[str]] = {f.module: set() for f in facts}
    for f in facts:
        pkg = f.module.rsplit(".", 1)[0] if "." in f.module else ""
        for imp in f.imports:
            target = imp
            if imp.startswith("."):
                dots = len(imp) - len(imp.lstrip("."))
                base = pkg.split(".") if pkg else []
                base = base[: len(base) - (dots - 1)] if dots > 1 else base
                target = ".".join([*base, imp.lstrip(".")]).strip(".")
            for mod in (target, *(f"{target}.{n}" for n in f.used_names if f"{target}.{n}" in fan_in)):
                if mod in fan_in and mod != f.module:
                    fan_in[mod].add(f.module)
    max_fan = max((len(v) for v in fan_in.values()), default=1) or 1
    all_used: Dict[str, Set[str]] = {}
    for f in facts:
        for n in f.used_names:
            all_used.setdefault(n, set()).add(f.module)
    all_strings = set().union(*(f.strings for f in facts)) if facts else set()
    max_loc = max((f.loc for f in facts), default=1) or 1
    max_cc = max((f.cc for f in facts), default=1) or 1
    max_dep = max((len(f.imports) for f in facts), default=1) or 1
    max_state = max((f.state for f in facts), default=1) or 1
    max_churn = max(churn.values(), default=1) or 1

    # Function-level redundancy across files.
    funcs = [fn for f in facts if include_tests or not f.is_test for fn in f.funcs][:MAX_FUNCS_COMPARED]
    test_refs: Dict[str, Set[str]] = {}
    for t in tests:
        for n in t.used_names:
            test_refs.setdefault(n, set()).add(t.rel)
    best: Dict[str, Tuple[float, str, float]] = {}
    for i, a in enumerate(funcs):
        for b in funcs[i + 1:]:
            if a.file == b.file or abs(a.loc - b.loc) > max(a.loc, b.loc) * 0.5:
                continue
            ast_sim = _jaccard(a.shingles, b.shingles)
            if ast_sim < SIM_THRESHOLD_FOR_PAIRS:
                continue
            red = S.redundancy(
                ast_sim, _jaccard(a.idents, b.idents),
                1.0 - min(abs(a.arity - b.arity), 4) / 4 * (0.5 if a.returns == b.returns else 1.0),
                _jaccard(test_refs.get(a.name, set()), test_refs.get(b.name, set())),
                1.0 if a.globals_used == b.globals_used else 0.0, w)
            for x, y in ((a, b), (b, a)):
                if red > best.get(x.file, (0.0, "", 0.0))[0]:
                    best[x.file] = (red, f"{y.file}::{y.name}", ast_sim)
    near_dupes: Dict[str, int] = {}
    for f in facts:
        near_dupes[f.rel] = sum(1 for fn in funcs if fn.file != f.rel and best.get(f.rel, (0, "", 0))[0] >= SIM_THRESHOLD_FOR_PAIRS
                                and best[f.rel][1].startswith(fn.file + "::"))

    scores: List[FileScore] = []
    for f in facts:
        if f.is_test and not include_tests:
            continue
        fin = len(fan_in.get(f.module, ()))
        leaf = f.module.rsplit(".", 1)[-1]
        refs_elsewhere = {n for n in f.defined if (all_used.get(n, set()) - {f.module})}
        unreferenced = 1.0 - (len(refs_elsewhere) / len(f.defined)) if f.defined else 0.0
        covered = any(f.module in t.imports or leaf in t.used_names or any(d in t.used_names for d in f.defined)
                      for t in tests)
        stale = min(age.get(f.rel, 365.0) / 365.0, 1.0)
        entry = f.is_entry or leaf in {"__main__", "cli", "conftest", "setup", "__init__"} or f.module in entry_strings
        unreachable = 0.0 if (fin or entry) else 1.0
        unused_export = (len(f.exported - set(all_used)) / len(f.exported)) if f.exported else 0.0
        dynamic = 1.0 if (f.module in all_strings or leaf in all_strings or f.module in entry_strings) else 0.0
        pdead = S.dead_probability(unreferenced, 0.0 if covered else 1.0, stale, unreachable, unused_export, dynamic, w)

        ex = _level(_matches(f.imports, EXPOSURE_MODS))
        priv = _level(_matches(f.calls | f.imports, PRIV_CALLS))
        mut = _level(_matches(f.calls, MUT_CALLS))
        unsrc = _level(_matches(f.calls | f.used_names, UNSRC_CALLS))
        reach = 1.0 - unreachable * 0.75
        # env/argv/stdin input is a process boundary even without a network listener
        tbr = S.trust_boundary_risk(max(ex, 0.25 if (entry or unsrc) else 0.0), priv, mut, unsrc, reach)

        loc_n, cc_n = f.loc / max_loc, f.cc / max_cc
        dep_n, st_n = len(f.imports) / max_dep, f.state / max_state
        fin_n = fin / max_fan
        churn_n = churn.get(f.rel, 0) / max_churn
        severity = 1.0 if f.syntax_error else min(1.0, 0.25 * f.defects + tbr)
        rp = S.repair_priority(severity, max(fin_n, 0.1), max(churn_n, 0.1), max(fin_n, 0.1),
                               max(tbr, 0.1 if f.defects else 0.0), loc_n)
        red, peer, ast_sim = best.get(f.rel, (0.0, None, 0.0))
        dv = S.delete_value(cc_n, dep_n, st_n, min(1.0, 0.25 * f.defects), tbr, 1.0 - pdead, fin_n)
        mv = S.merge_value(ast_sim, cc_n, st_n, red, max(fin_n, tbr))
        pv = S.parameterization_value(min(near_dupes.get(f.rel, 0) / 3.0, 1.0), red, 1.0 - churn_n,
                                      min(sum(fn.arity for fn in f.funcs) / max(len(f.funcs), 1) / 8.0, 1.0), tbr)
        decision = S.select_action(dv=dv, mv=mv, pv=pv, rp=rp, pdead=pdead, red=red, tbr=tbr, weights=w)

        public_n = len(f.public) / len(f.defined) if f.defined else 0.0
        nondet = 1.0 if _matches(f.calls, NONDET) else 0.0
        id_now = S.intelligence_density(1.0 - pdead, max(fin_n, 0.1), max(public_n, 0.1), 1.0 if covered else 0.3,
                                        1.0 - 0.5 * nondet, loc_n, cc_n, dep_n, st_n)
        before = S.Metrics(f.loc, f.cc, len(f.imports), f.state)
        if decision.action is S.CleanupAction.DELETE:
            after, cap_delta = S.Metrics(0, 0, 0, 0), -(1.0 - pdead)
            id_after = 0.0
        elif decision.action in (S.CleanupAction.MERGE, S.CleanupAction.PARAMETERIZE):
            # merge folds the duplicated half away; parameterizing keeps one body plus a flag
            k = 1.0 - (0.5 if decision.action is S.CleanupAction.MERGE else 0.3) * red
            after, cap_delta = S.Metrics(int(f.loc * k), max(int(f.cc * k), 1), len(f.imports), f.state), 0.0
            id_after = S.intelligence_density(1.0 - pdead, max(fin_n, 0.1), max(public_n, 0.1), 1.0 if covered else 0.3,
                                              1.0 - 0.5 * nondet, loc_n * k, cc_n * k, dep_n, st_n)
        else:
            after, cap_delta, id_after = before, 0.0, id_now
        obligations = sorted({t.rel for t in tests if f.module in t.imports or leaf in t.used_names})
        if decision.action is not S.CleanupAction.KEEP and not obligations:
            obligations = [f"characterization test for {f.module} before {decision.action.value}"]

        scores.append(FileScore(
            file=f.rel, module=f.module,
            metrics={"loc": f.loc, "cc": f.cc, "deps": len(f.imports), "state": f.state, "fan_in": fin, "defects": f.defects},
            signals={"unreferenced": round(unreferenced, 3), "covered": float(covered), "stale": round(stale, 3),
                     "unreachable": unreachable, "unused_export": round(unused_export, 3), "dynamic_use": dynamic,
                     "EX": ex, "PRIV": priv, "MUT": mut, "UNSRC": unsrc, "REACH": reach},
            ID=round(id_now, 4), RP=round(rp, 4), RED=round(red, 4), RED_peer=peer, DV=round(dv, 4),
            MV=round(mv, 4), PV=round(pv, 4), Pdead=round(pdead, 4), TBR=round(tbr, 4),
            action=decision.action.value, action_value=round(decision.value, 4), requires_review=decision.requires_review,
            blocked=decision.blocked, expected_SG=round(S.simplification_gain(before, after), 4),
            capability_delta=round(cap_delta, 4), delta_ID=round(id_after - id_now, 4), test_obligations=obligations,
        ))

    def ranked(key: str) -> List[str]:
        return [s.file for s in sorted(scores, key=lambda s: (-getattr(s, key), s.file))][: top or len(scores)]

    proposed = [s for s in scores if s.action != S.CleanupAction.KEEP.value]
    report = {
        "root": str(root),
        "files_scored": len(scores),
        "weights": w,
        "rank_by": {"RP": ranked("RP"), "RED": ranked("RED"), "TBR": ranked("TBR")},
        "actions": {a.value: sum(1 for s in scores if s.action == a.value) for a in S.CleanupAction},
        "proposed": [S.as_dict(s) for s in sorted(proposed, key=lambda s: (-s.action_value, s.file))][: top or None],
        "J_if_all_accepted": round(S.net_objective(
            [{"sg": s.expected_SG, "capability_delta": s.capability_delta, "tbr_after": 0.0 if s.action == "DELETE" else s.TBR}
             for s in proposed]), 4),
        "mutations": 0,
        "note": "report-only; DELETE/MERGE proposals require review and refactor_acceptance evidence before any change",
    }
    report["files"] = [S.as_dict(s) for s in scores]
    return report
