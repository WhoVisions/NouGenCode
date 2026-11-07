import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class BaseStoryEngineIntentTest(unittest.IsolatedAsyncioTestCase):
    """Shared parameterized test suite for StoryEngine intent routing and prompt specialization."""
    engine_module_name = "EdgeNode.story.engine"

    def create_story_engine(self):
        try:
            from EdgeNode.story.engine import StoryEngine
            return StoryEngine(world_config={"world_id": "test_eval"})
        except ImportError:
            mock = MagicMock()
            mock.scene = 1
            mock.pov = "first"
            mock.mode = MagicMock(value="creative")
            return mock

    def setUp(self):
        # Initialize Engine with mocked client
        self.engine = self.create_story_engine()
        self.engine.client = MagicMock()
        self.engine.context = MagicMock()
        self.engine.context.get_budget_status.return_value = {"should_prune": False}
        self.engine.context.update_cache.return_value = None
        self.engine.console = MagicMock()
        
        # Mock Components
        self.engine.router = MagicMock()
        self.engine.router.route.return_value = {"intent": "plan", "should_write_scene": False}
        self.engine.router.create_plan = AsyncMock(return_value="[PLANNER OUPUT]")
        
        self.engine.prompts = MagicMock()
        self.engine.prompts.build.return_value = "[SYSTEM PROMPT] [LORE-FIRST PROTOCOL] Never contradict the bible"
        
        self.engine.generate_canon_pack = AsyncMock(return_value="[SCENE OUTPUT]")
        self.engine._ensure_author_questions = MagicMock(side_effect=lambda x: x)
        self.engine._sync_lighting = MagicMock()

    async def test_cli_plan_shortcut(self):
        """Test :plan shortcut bypasses router and calls planner."""
        print("\n🧪 Testing :plan shortcut...")
        await self.engine._execute_turn(":plan build a castle")
        self.engine.router.route.assert_not_called()
        self.engine.router.create_plan.assert_called_once()
        args, _ = self.engine.router.create_plan.call_args
        self.assertIn("build a castle", args[0])
        print("✅ :plan shortcut bypassed router successfully.")

    async def test_cli_scene_shortcut(self):
        """Test :scene shortcut bypasses router and calls generator."""
        print("\n🧪 Testing :scene shortcut...")
        await self.engine._execute_turn(":scene fight the dragon", tick_physics=False)
        self.engine.router.route.assert_not_called()
        self.engine.generate_canon_pack.assert_called_once()
        print("✅ :scene shortcut triggered generation successfully.")

    async def test_auto_router_plan(self):
        """Test standard input uses router -> Plan."""
        print("\n🧪 Testing Auto-Router (Plan)...")
        self.engine.router.route.return_value = {
            "intent": "plan", 
            "should_write_scene": False,
            "needs_tools": False
        }
        await self.engine._execute_turn("kush kingdom")
        self.engine.router.route.assert_called_once()
        self.engine.router.create_plan.assert_called_once()
        print("✅ Auto-Router correctly routed to Planner.")

    async def test_prompt_specialization(self):
        """Verify prompt builder modes."""
        print("\n🧪 Testing Prompt Specialization...")
        try:
            patcher = patch(f"{self.engine_module_name}.doctrine_directives", return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)
        except (ImportError, ModuleNotFoundError):
            pass

        self.engine.prompts.build.reset_mock()
        await self.engine._execute_turn(":scene test", tick_physics=False)
        self.engine.prompts.build.assert_called_with(
            self.engine.scene - 1, self.engine.pov, self.engine.mode.value, directives=[], mode_arg="writer"
        )
        
        self.engine.prompts.build.reset_mock()
        await self.engine._execute_turn(":plan test", tick_physics=False)
        call_args = self.engine.prompts.build.call_args
        self.assertEqual(call_args.kwargs['mode_arg'], "planner")
        print("✅ Planner prompt is clean; Writer prompt has protocols.")


class TestStoryEngineIntent(BaseStoryEngineIntentTest):
    """Concrete test class for EdgeNode implementation."""
    engine_module_name = "EdgeNode.story.engine"


if __name__ == "__main__":
    unittest.main()
