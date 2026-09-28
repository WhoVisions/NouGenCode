#!/usr/bin/env python3
"""Fan a review across every healthy free route and take a majority vote.

Coach mode: the fleet reviews, this script only tallies. One model's opinion of
its own code is worth little; the point is independent routes disagreeing.

Writes the transcript to analysis/ (never the scratchpad — Rule 0.5.2).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"~/Outpost\NouGen\tools")
from fleet import Fleet  # noqa: E402

GUARD = Path(r"~/Outpost\NouGenRelay\src\nougen_relay\agy_hook.py").read_text(encoding="utf-8")

PROMPT = f"""You are reviewing a security-adjacent guard before it ships. Be adversarial.

Context: several machines edit the same git repos. Before editing, a machine must
"claim" a scope. This hook runs before every file-edit tool and decides: allow,
ask, or deny. It fails OPEN (allow) on any internal error, deliberately.

```python
{GUARD}
```

Answer ONLY in this format, no preamble:

VERDICT: SHIP or HOLD
TOP_RISK: <the single most serious concrete failure mode, one sentence>
BYPASS: <one concrete way an agent could edit a file another machine claimed, or NONE>

Be specific. Do not restate the docstring back to me."""


def main():
    f = Fleet()
    f.probe(verbose=False)
    n = min(len(f.healthy), 12)  # a judgement call, not a scale test
    if not n:
        print("no healthy routes"); return 1
    print(f"dispatching {n} independent reviews across the free fleet...", flush=True)

    # map() fans across ALL healthy routes and returns (index, route_name, output)
    results = f.map([PROMPT] * n)

    out, ship, hold = [], 0, 0
    for _idx, name, res in results:
        text = (res or "").strip() if isinstance(res, str) else str(res).strip()
        if not text or "error" in text.lower()[:40]:
            out.append({"route": name, "status": "no-answer", "raw": text[:200]}); continue
        verdict = "SHIP" if "VERDICT: SHIP" in text.upper() else ("HOLD" if "VERDICT: HOLD" in text.upper() else "?")
        ship += verdict == "SHIP"; hold += verdict == "HOLD"
        out.append({"route": name, "verdict": verdict, "answer": text[:600]})

    analysis = Path(r"~/Outpost\NouGenRelay\analysis")
    analysis.mkdir(exist_ok=True)
    dest = analysis / "fleet-audit-agy-hook.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nVOTE: {ship} ship / {hold} hold / {len(out)-ship-hold} no-answer")
    print(f"transcript: {dest}\n")
    for o in out:
        if o.get("verdict") == "HOLD" or "BYPASS" in o.get("answer", ""):
            print(f"--- {o['route']} [{o.get('verdict')}]")
            for line in o.get("answer", "").splitlines():
                if line.strip().upper().startswith(("TOP_RISK", "BYPASS")):
                    print(f"    {line.strip()[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
