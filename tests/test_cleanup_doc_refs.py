"""A script named in a markdown doc is dynamically used, not unreferenced.

Found by the first NouGenCode self-pass (2026-10-05): both DELETE proposals were skill scripts
that their SKILL.md documents as the executable core, invoked by command line.
"""
import textwrap

from nougencode.cleanup import run_cleanup_pass

BODY = """
    import sys
    def main(argv):
        total = 0
        for a in argv:
            if a:
                total += len(a)
        return total
    if __name__ == "__main__":
        sys.exit(main(sys.argv[1:]))
"""


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))


def _file(report, rel):
    return {f["file"]: f for f in report["files"]}[rel]


def test_script_named_in_skill_doc_is_dynamic_use(tmp_path):
    _write(tmp_path, "skills/demo/scripts/demo_tool.py", BODY)
    _write(tmp_path, "skills/demo/SKILL.md", "Run `python scripts/demo_tool.py --help`.\n")
    _write(tmp_path, "skills/other/scripts/orphan_tool.py", BODY)
    report = run_cleanup_pass(tmp_path)
    documented = _file(report, "skills/demo/scripts/demo_tool.py")
    assert documented["signals"]["dynamic_use"] == 1.0
    assert documented["action"] != "DELETE"


def test_script_not_named_anywhere_stays_unreferenced(tmp_path):
    # negative control: without a doc mention the same code still carries no dynamic-use evidence
    _write(tmp_path, "skills/demo/scripts/demo_tool.py", BODY)
    _write(tmp_path, "skills/demo/SKILL.md", "No script mentioned here.\n")
    report = run_cleanup_pass(tmp_path)
    assert _file(report, "skills/demo/scripts/demo_tool.py")["signals"]["dynamic_use"] == 0.0
