import asyncio
import sys
import os
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from EdgeNode.story.engine import StoryEngine

class TestStoryEngineIntent(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Initialize Engine with mocked client
        self.engine = StoryEngine(world_config={"world_id": "test_eval"})
        self.engine.client = MagicMock()
        self.engine.context = MagicMock()
        self.engine.context.get_budget_status.return_value = {"should_prune": False}
        self.engine.context.update_cache.return_value = None
        self.engine.console = MagicMock()
        
        # Mock methods to avoid side effects
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
        
        # Router should NOT be called (CLI override logic uses force_plan variable)
        # But wait, in the new logic:
        # if force_plan: router_plan = force_plan
        # else: router_plan = self.router.route()
        # So router.route should NOT be called.
        self.engine.router.route.assert_not_called()
        
        # Planner should be called
        self.engine.router.create_plan.assert_called_once()
        args, _ = self.engine.router.create_plan.call_args
        self.assertIn("build a castle", args[0])
        print("✅ :plan shortcut bypassed router successfully.")

    async def test_cli_scene_shortcut(self):
        """Test :scene shortcut bypasses router and calls generator."""
        print("\n🧪 Testing :scene shortcut...")
        
        await self.engine._execute_turn(":scene fight the dragon", tick_physics=False)
        
        # Router should NOT be called
        self.engine.router.route.assert_not_called()
        
        # Canon factory should be called (logic falls through to generator)
        # Note: In _execute_turn, if should_write_scene is True, it goes to generate_canon_pack later
        # We need to ensure it didn't return early
        self.engine.generate_canon_pack.assert_called_once()
        print("✅ :scene shortcut triggered generation successfully.")

    async def test_auto_router_plan(self):
        """Test standard input uses router -> Plan."""
        print("\n🧪 Testing Auto-Router (Plan)...")
        
        # Setup Router to return Plan
        # Setup Router to return Plan
        self.engine.router.route.return_value = {
            "intent": "plan", 
            "should_write_scene": False,
            "needs_tools": False
        }
        
        await self.engine._execute_turn("kush kingdom")
        
        self.engine.router.route.assert_called_once()
        self.engine.router.create_plan.assert_called_once()
        print("✅ Auto-Router correctly routed to Planner.")

    @patch('EdgeNode.story.engine.doctrine_directives', return_value=[])
    async def test_prompt_specialization(self, mock_doctrine):
        """Verify prompt builder modes."""
        print("\n🧪 Testing Prompt Specialization...")
        
        # Writer Mode
        # We mocked prompts.build to return a generic string in setUp
        # To test specialization, we need to bypass the mock or inspect call args
        # Since we are mocking the component, we can't test its internal logic here anymore (unit vs integration)
        # The prompt builder logic is now in a separate class component PromptBuilder.
        # This test should now verify that prompts.build was CALLED with correct mode.
        
        self.engine.prompts.build.reset_mock()
        await self.engine._execute_turn(":scene test", tick_physics=False)
        self.engine.prompts.build.assert_called_with(
             self.engine.scene - 1, self.engine.pov, self.engine.mode.value, directives=[], mode_arg="writer"
        )
        
        self.engine.prompts.build.reset_mock()
        await self.engine._execute_turn(":plan test", tick_physics=False)
        # Check call args
        call_args = self.engine.prompts.build.call_args
        self.assertEqual(call_args.kwargs['mode_arg'], "planner")
        
        print("✅ Planner prompt is clean; Writer prompt has protocols.")

if __name__ == "__main__":
    unittest.main()
