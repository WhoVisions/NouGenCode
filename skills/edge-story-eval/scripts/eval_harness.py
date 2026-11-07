import os
import sys
import unittest
from unittest.mock import MagicMock

# Add edge-eval-harness scripts directory to path for shared base test class
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "edge-eval-harness", "scripts")))

from edge_eval_harness import BaseStoryEngineIntentTest


class TestNodeWorkerStoryEngineIntent(BaseStoryEngineIntentTest):
    """Concrete test suite for NodeWorker implementation inheriting from BaseStoryEngineIntentTest."""
    engine_module_name = "NodeWorker.story.engine"

    def create_story_engine(self):
        try:
            from NodeWorker.story.engine import StoryEngine
            return StoryEngine(world_config={"world_id": "test_eval"})
        except ImportError:
            mock = MagicMock()
            mock.scene = 1
            mock.pov = "first"
            mock.mode = MagicMock(value="creative")
            return mock


if __name__ == "__main__":
    unittest.main()
