import sys
import asyncio
import random
import logging
# Ensure NodeWorker package is in path
import os
sys.path.append(os.getcwd())

from NodeWorker.story.engine import StoryEngine

# Configure logging
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("NodeWorker")

async def run_smoke_test():
    print("=== STARTING 25 TURN SMOKE TEST ===")
    
    try:
        engine = StoryEngine()
        print("[*] Engine Initialized")
        
        # Mock Tension to avoid World dependency
        class MockTension:
            @property
            def current(self): return 0.5
        engine.tension = MockTension()
        print("[*] Tension Subsystem Mocked")
        
    except Exception as e:
        print(f"[CRITICAL] Engine failed to init: {e}")
        return

    commands = [
        ":lights wave color=cyan period=0.5",
        ":lights rainbow period=1.0",
        ":lights lightning base=blue",
        ":lights tension color=red",
        ":lights stop",
        ":lights fire brightness=0.8",
        ":lights breathe color=green period=0.5",
        ":lights color hue=0.5 sat=1.0 bright=1.0",
        ":lights restore"
    ]
    
    print("[*] Starting Loop...", flush=True)
    for i in range(1, 26):
        cmd = random.choice(commands)
        print(f"\n[Turn {i}/25] Sending: {cmd}", flush=True)
        
        try:
            # We call _execute_turn directly
            # Pass tick_physics=False to avoid needing a full World simulation
            resp = await engine._execute_turn(cmd, tick_physics=False)
            print(f"   -> Response: {resp.text}", flush=True)
            
            # Brief pause to let effects start and run a bit
            await asyncio.sleep(0.4)
            
        except Exception as e:
            print(f"\n[FAIL] Turn {i} crashed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
    print("\n=== SMOKE TEST PASSED (25 Turns) ===")
    
    # Cleanup
    try:
        if engine.lights:
            engine.lights.stop()
            engine.lights.restore()
            if engine.lights.razer:
                engine.lights.razer.close()
    except: pass

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(run_smoke_test())
    except KeyboardInterrupt:
        pass
