import tempfile
from pathlib import Path
from nougencode.skills_engine import SkillRegistry

def test_create_skill():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        registry = SkillRegistry(extra_roots=[tmp_path])
        skill = registry.create_skill(
            name="test-analyzer",
            description="Analyzes code test metrics",
            instructions="1. Run pytest\n2. Report results",
            target_dir=tmp_path
        )
        assert skill.name == "test-analyzer"
        assert skill.path.exists()
        assert "Analyzes code test metrics" in skill.path.read_text(encoding="utf-8")
        assert registry.get_skill("test-analyzer") is not None
