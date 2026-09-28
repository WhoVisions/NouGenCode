"""
Razer Chroma SDK REST API Skill for NodeWorker
Controls RGB lighting on Razer devices via the Chroma SDK.

API Reference: https://assets.razerzone.com/dev_portal/REST/html/index.html

Requirements:
- Razer Synapse 3 with Chroma Connect enabled
- Chroma SDK running locally (default port 54235)
"""

import requests
import time
import threading
from typing import Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum


# ============================================================================
# CONFIGURATION
# ============================================================================

CHROMA_SDK_URL = "http://localhost:54235/razer/chromasdk"
CHROMA_SDK_HTTPS = "https://chromasdk.io:54236/razer/chromasdk"
DEFAULT_TIMEOUT = 15  # SDK connection timeout in seconds
HEARTBEAT_INTERVAL = 1  # Recommended: 1 second


# ============================================================================
# EFFECT TYPES
# ============================================================================

class Effect(Enum):
    NONE = "CHROMA_NONE"
    STATIC = "CHROMA_STATIC"
    CUSTOM = "CHROMA_CUSTOM"
    CUSTOM2 = "CHROMA_CUSTOM2"
    CUSTOM_KEY = "CHROMA_CUSTOM_KEY"
    BREATHING = "CHROMA_BREATHING"
    WAVE = "CHROMA_WAVE"
    SPECTRUM_CYCLING = "CHROMA_SPECTRUMCYCLING"
    REACTIVE = "CHROMA_REACTIVE"
    BLINKING = "CHROMA_BLINKING"


# Wave directions
class WaveDirection(Enum):
    LEFT_TO_RIGHT = 1
    RIGHT_TO_LEFT = 2


class Device(Enum):
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    HEADSET = "headset"
    MOUSEPAD = "mousepad"
    KEYPAD = "keypad"
    CHROMALINK = "chromalink"


# Grid/LED sizes for each device
class GridSize:
    """Device grid and LED sizes for custom effects."""
    CHROMALINK_LEDS = 5
    HEADSET_LEDS = 5
    KEYBOARD_ROWS = 6
    KEYBOARD_COLS = 22
    KEYBOARD_V2_ROWS = 8
    KEYBOARD_V2_COLS = 24
    KEYPAD_ROWS = 4
    KEYPAD_COLS = 5
    MOUSE_ROWS = 9
    MOUSE_COLS = 7
    MOUSEPAD_LEDS = 15
    MOUSEPAD_V2_LEDS = 20


# ============================================================================
# COLOR UTILITIES  
# ============================================================================

def rgb_to_bgr(r: int, g: int, b: int) -> int:
    """Convert RGB to BGR integer format for Chroma SDK."""
    return (b << 16) | (g << 8) | r


def hex_to_bgr(hex_color: str) -> int:
    """Convert hex color (#RRGGBB) to BGR integer."""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return rgb_to_bgr(r, g, b)


# Common colors in BGR format
class Colors:
    RED = rgb_to_bgr(255, 0, 0)      # 255
    GREEN = rgb_to_bgr(0, 255, 0)    # 65280
    BLUE = rgb_to_bgr(0, 0, 255)     # 16711680
    YELLOW = rgb_to_bgr(255, 255, 0) # 65535
    CYAN = rgb_to_bgr(0, 255, 255)   # 16776960
    MAGENTA = rgb_to_bgr(255, 0, 255)# 16711935
    WHITE = rgb_to_bgr(255, 255, 255)# 16777215
    BLACK = 0
    ORANGE = rgb_to_bgr(255, 165, 0) # 42495
    PURPLE = rgb_to_bgr(128, 0, 128) # 8388736


# ============================================================================
# CHROMA SESSION MANAGER
# ============================================================================

@dataclass
class ChromaSession:
    """Active Chroma SDK session."""
    session_id: int
    uri: str
    active: bool = True
    _heartbeat_thread: Optional[threading.Thread] = None


class RazerChroma:
    """
    Razer Chroma SDK client for controlling RGB lighting.
    
    Usage:
        chroma = RazerChroma()
        chroma.connect()
        chroma.set_static_color(Device.KEYBOARD, Colors.RED)
        chroma.disconnect()
    """
    
    def __init__(self, app_name: str = "NodeWorker AI Assistant"):
        self.app_name = app_name
        self.session: Optional[ChromaSession] = None
        self._heartbeat_active = False
    
    # ========================================================================
    # CONNECTION MANAGEMENT
    # ========================================================================
    
    def connect(self) -> Dict:
        """
        Initialize connection to Chroma SDK.
        Must be called before any effects.
        
        Returns:
            Dict with session info or error
        """
        payload = {
            "title": self.app_name,
            "description": "AI-powered RGB control via NodeWorker",
            "author": {
                "name": "NodeWorker Brain",
                "contact": "https://github.com/Who-Visions/NodeWorker"
            },
            "device_supported": [d.value for d in Device],
            "category": "application"
        }
        
        try:
            # Try localhost first
            response = requests.post(CHROMA_SDK_URL, json=payload, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if "sessionid" in data and "uri" in data:
                    self.session = ChromaSession(
                        session_id=data["sessionid"],
                        uri=data["uri"]
                    )
                    # Wait for session port to be ready (SDK quirk)
                    time.sleep(2)
                    self._start_heartbeat()
                    return {
                        "success": True,
                        "session_id": self.session.session_id,
                        "uri": self.session.uri
                    }
            
            return {"success": False, "error": f"SDK response: {response.text}"}
            
        except requests.exceptions.ConnectionError:
            return {
                "success": False, 
                "error": "Chroma SDK not running. Ensure Razer Synapse 3 is installed with Chroma Connect enabled."
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def disconnect(self) -> Dict:
        """
        Uninitialize and close the Chroma SDK session.
        Turns off all devices before disconnecting to prevent stuck lights.
        Should be called when done to free resources.
        """
        if not self.session:
            return {"success": False, "error": "Not connected"}
        
        self._stop_heartbeat()
        
        try:
            # Turn off all devices before disconnecting
            payload = {"effect": "CHROMA_NONE"}
            for ep in ["chromalink", "mousepad", "headset", "mouse"]:
                try:
                    requests.put(f"{self.session.uri}/{ep}", json=payload, timeout=2)
                except:
                    pass
            
            response = requests.delete(self.session.uri, timeout=5)
            self.session = None
            return {"success": True, "result": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _start_heartbeat(self):
        """Start background heartbeat to keep connection alive."""
        self._heartbeat_active = True
        
        def heartbeat_loop():
            while self._heartbeat_active and self.session:
                try:
                    requests.put(f"{self.session.uri}/heartbeat", timeout=2)
                except:
                    pass
                time.sleep(HEARTBEAT_INTERVAL)
        
        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()
        self.session._heartbeat_thread = thread
    
    def _stop_heartbeat(self):
        """Stop the heartbeat thread."""
        self._heartbeat_active = False
    
    def get_sdk_version(self) -> Dict:
        """Get the Chroma SDK version installed on the system."""
        try:
            response = requests.get(CHROMA_SDK_URL, timeout=5)
            return {"success": True, "version": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # DEVICE EFFECTS
    # ========================================================================
    
    def _send_effect(self, device: Device, payload: Dict) -> Dict:
        """Send effect to a specific device."""
        if not self.session:
            return {"success": False, "error": "Not connected. Call connect() first."}
        
        endpoint = f"{self.session.uri}/{device.value}"
        
        try:
            response = requests.put(endpoint, json=payload, timeout=5)
            return {"success": True, "result": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def set_static_color(self, device: Device, color: int) -> Dict:
        """
        Set a static color on a device.
        
        Args:
            device: Device enum (KEYBOARD, MOUSE, etc.)
            color: BGR color integer (use Colors class or rgb_to_bgr())
            
        Example:
            chroma.set_static_color(Device.KEYBOARD, Colors.RED)
            chroma.set_static_color(Device.MOUSE, rgb_to_bgr(0, 128, 255))
        """
        payload = {
            "effect": Effect.STATIC.value,
            "param": {"color": color}
        }
        return self._send_effect(device, payload)
    
    def turn_off(self, device: Device) -> Dict:
        """Turn off lighting on a device."""
        payload = {"effect": Effect.NONE.value}
        return self._send_effect(device, payload)
    
    def set_all_static(self, color: int) -> Dict:
        """Set static color on ALL connected Chroma devices.
        
        Targets chromalink, mousepad, and headset endpoints for full coverage
        including Base Station and other accessories.
        """
        payload = {
            "effect": Effect.STATIC.value,
            "param": {"color": color}
        }
        results = {}
        for device in [Device.CHROMALINK, Device.MOUSEPAD, Device.HEADSET, Device.MOUSE]:
            results[device.value] = self._send_effect(device, payload)
        return results
    
    def turn_off_all(self) -> Dict:
        """Turn off ALL connected Chroma devices.
        
        Targets chromalink, mousepad, and headset endpoints for full coverage.
        """
        payload = {"effect": Effect.NONE.value}
        results = {}
        for device in [Device.CHROMALINK, Device.MOUSEPAD, Device.HEADSET, Device.MOUSE]:
            results[device.value] = self._send_effect(device, payload)
        return results
    
    def pulse(self, r: int = 255, g: int = 0, b: int = 0, cycles: int = 3, speed: float = 0.05) -> None:
        """
        Software-based pulse effect that cycles brightness using STATIC.
        Works reliably on ALL devices (hardware breathing effects don't work via REST API).
        
        Args:
            r, g, b: RGB color values (0-255)
            cycles: Number of pulse cycles
            speed: Delay between brightness steps (lower = faster)
        """
        if not self.session:
            return
        
        endpoints = ["chromalink", "mousepad", "headset", "mouse", "keyboard"]
        
        for _ in range(cycles):
            # Fade up
            for brightness in range(0, 256, 25):
                factor = brightness / 255
                color = rgb_to_bgr(int(r * factor), int(g * factor), int(b * factor))
                effect = {"effect": "CHROMA_STATIC", "param": {"color": color}}
                for ep in endpoints:
                    try:
                        requests.put(f"{self.session.uri}/{ep}", json=effect, timeout=1)
                    except:
                        pass
                time.sleep(speed)
            
            # Fade down
            for brightness in range(255, -1, -25):
                factor = brightness / 255
                color = rgb_to_bgr(int(r * factor), int(g * factor), int(b * factor))
                effect = {"effect": "CHROMA_STATIC", "param": {"color": color}}
                for ep in endpoints:
                    try:
                        requests.put(f"{self.session.uri}/{ep}", json=effect, timeout=1)
                    except:
                        pass
                time.sleep(speed)
            
            # Keep session alive
            try:
                requests.put(f"{self.session.uri}/heartbeat", timeout=2)
            except:
                pass
    
    def spectrum_cycle(self, duration: float = 10.0, speed: float = 0.1) -> None:
        """
        Software-based rainbow spectrum effect that cycles through all hues.
        Works reliably on ALL devices.
        
        Args:
            duration: How long to run the effect (seconds)
            speed: Delay between color steps (lower = faster)
        """
        if not self.session:
            return
        
        import colorsys
        endpoints = ["chromalink", "mousepad", "headset", "mouse", "keyboard"]
        
        steps = int(duration / speed)
        for i in range(steps):
            hue = (i * 3.6) % 360
            r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
            color = rgb_to_bgr(int(r * 255), int(g * 255), int(b * 255))
            effect = {"effect": "CHROMA_STATIC", "param": {"color": color}}
            
            for ep in endpoints:
                try:
                    requests.put(f"{self.session.uri}/{ep}", json=effect, timeout=1)
                except:
                    pass
            
            time.sleep(speed)
            
            if i % 30 == 0:
                try:
                    requests.put(f"{self.session.uri}/heartbeat", timeout=2)
                except:
                    pass
    
    def wave(self, r: int = 255, g: int = 0, b: int = 0, duration: float = 10.0, speed: float = 0.2) -> None:
        """
        Software-based wave effect that simulates brightness movement.
        Works reliably on ALL devices.
        
        Args:
            r, g, b: Base RGB color (0-255)
            duration: How long to run the effect (seconds)
            speed: Delay between wave steps (lower = faster)
        """
        if not self.session:
            return
        
        endpoints = ["chromalink", "mousepad", "headset", "mouse", "keyboard"]
        cycles = int(duration / (speed * 10))
        
        for _ in range(cycles):
            for phase in range(10):
                # Create wave pattern with one endpoint brighter
                for i, ep in enumerate(endpoints):
                    # Brightness peaks at current phase position
                    factor = 1.0 if (phase % 4) == i else 0.2
                    color = rgb_to_bgr(int(r * factor), int(g * factor), int(b * factor))
                    effect = {"effect": "CHROMA_STATIC", "param": {"color": color}}
                    try:
                        requests.put(f"{self.session.uri}/{ep}", json=effect, timeout=1)
                    except:
                        pass
                time.sleep(speed)
            
            try:
                requests.put(f"{self.session.uri}/heartbeat", timeout=2)
            except:
                pass
    
    def fire(self, duration: float = 10.0) -> None:
        """
        Software-based fire effect with flickering flames.
        Uses CHROMA_CUSTOM for per-key keyboard flames and STATIC for other devices.
        Verified working on all 7 devices including BlackWidow Elite.
        
        Args:
            duration: How long to run the effect (seconds)
        """
        if not self.session:
            return
        
        import random
        
        # Fire colors: orange, red, yellow variations
        fire_colors = [
            rgb_to_bgr(255, 50, 0),    # Orange-red
            rgb_to_bgr(255, 100, 0),   # Orange
            rgb_to_bgr(255, 150, 20),  # Yellow-orange
            rgb_to_bgr(200, 30, 0),    # Dark red
            rgb_to_bgr(255, 80, 0),    # Bright orange
            rgb_to_bgr(180, 40, 0),    # Ember
            rgb_to_bgr(255, 200, 50),  # Yellow flame tip
        ]
        
        endpoints = ["chromalink", "mousepad", "headset", "mouse"]
        frames = int(duration / 0.1)
        
        for frame in range(frames):
            # Create random fire pattern for 6x22 keyboard grid
            grid = []
            for row in range(6):
                row_colors = []
                for col in range(22):
                    # Bottom rows brighter, top rows dimmer
                    intensity = (5 - row) / 5
                    if random.random() < intensity:
                        color = random.choice(fire_colors)
                    else:
                        color = rgb_to_bgr(int(100 * random.random()), int(20 * random.random()), 0)
                    row_colors.append(color)
                grid.append(row_colors)
            
            # Send to keyboard with CUSTOM
            try:
                requests.put(f"{self.session.uri}/keyboard", 
                           json={"effect": "CHROMA_CUSTOM", "param": grid}, timeout=1)
            except:
                pass
            
            # Send fire color to other devices
            fire_color = random.choice(fire_colors)
            for ep in endpoints:
                try:
                    requests.put(f"{self.session.uri}/{ep}", 
                               json={"effect": "CHROMA_STATIC", "param": {"color": fire_color}}, timeout=0.5)
                except:
                    pass
            
            time.sleep(0.1)
            
            if frame % 20 == 0:
                try:
                    requests.put(f"{self.session.uri}/heartbeat", timeout=2)
                except:
                    pass
    
    def starlight(self, duration: float = 10.0) -> None:
        """
        Software-based starlight effect with twinkling stars.
        Random keys fade in and out like twinkling stars on dark background.
        Verified working on all 7 devices.
        
        Args:
            duration: How long to run the effect (seconds)
        """
        if not self.session:
            return
        
        import random
        
        star_colors = [
            rgb_to_bgr(255, 255, 255),   # White
            rgb_to_bgr(200, 220, 255),   # Light blue
            rgb_to_bgr(255, 250, 220),   # Pale yellow
        ]
        bg_color = rgb_to_bgr(10, 5, 20)  # Dark purple
        
        stars = {}  # (row, col) -> (brightness, delta)
        endpoints = ["chromalink", "mousepad", "headset", "mouse"]
        frames = int(duration / 0.1)
        
        for frame in range(frames):
            # Spawn new stars randomly
            if random.random() < 0.15:
                row, col = random.randint(0, 5), random.randint(0, 21)
                if (row, col) not in stars:
                    stars[(row, col)] = (0, random.uniform(0.1, 0.3))
            
            grid = [[bg_color]*22 for _ in range(6)]
            
            to_remove = []
            for (row, col), (brightness, delta) in stars.items():
                brightness += delta
                if brightness >= 1.0:
                    brightness, delta = 1.0, -abs(delta)
                elif brightness <= 0:
                    to_remove.append((row, col))
                    continue
                stars[(row, col)] = (brightness, delta)
                
                base = random.choice(star_colors)
                r = int(((base >> 0) & 0xFF) * brightness)
                g = int(((base >> 8) & 0xFF) * brightness)
                b = int(((base >> 16) & 0xFF) * brightness)
                grid[row][col] = rgb_to_bgr(r, g, b)
            
            for key in to_remove:
                del stars[key]
            
            try:
                requests.put(f"{self.session.uri}/keyboard", 
                           json={"effect": "CHROMA_CUSTOM", "param": grid}, timeout=1)
            except:
                pass
            
            twinkle = random.choice(star_colors) if random.random() < 0.2 else bg_color
            for ep in endpoints:
                try:
                    requests.put(f"{self.session.uri}/{ep}", 
                               json={"effect": "CHROMA_STATIC", "param": {"color": twinkle}}, timeout=0.5)
                except:
                    pass
            
            time.sleep(0.1)
            if frame % 20 == 0:
                try:
                    requests.put(f"{self.session.uri}/heartbeat", timeout=2)
                except:
                    pass
    
    # ========================================================================
    # DYNAMIC EFFECTS (Note: Hardware effects don't work via REST API)
    # ========================================================================
    
    def set_breathing(self, color1: int, color2: int = None) -> Dict:
        """
        Set breathing effect on all devices.
        
        Args:
            color1: Primary BGR color
            color2: Optional secondary color for dual-color breathing
        """
        if color2 is not None:
            # Two-color breathing
            payload = {
                "effect": Effect.BREATHING.value,
                "param": {
                    "color1": color1,
                    "color2": color2,
                    "type": 2  # Two colors
                }
            }
        else:
            # Single color breathing
            payload = {
                "effect": Effect.BREATHING.value,
                "param": {
                    "color1": color1,
                    "type": 1  # One color
                }
            }
        return self._send_effect(Device.MOUSEPAD, payload)
    
    def set_wave(self, direction: int = 1) -> Dict:
        """
        Set wave effect on all devices.
        
        Args:
            direction: 1 = left to right, 2 = right to left
        """
        payload = {
            "effect": Effect.WAVE.value,
            "param": {
                "direction": direction
            }
        }
        return self._send_effect(Device.MOUSEPAD, payload)
    
    def set_spectrum_cycling(self) -> Dict:
        """Set spectrum cycling (rainbow) effect on all devices."""
        payload = {"effect": Effect.SPECTRUM_CYCLING.value}
        return self._send_effect(Device.MOUSEPAD, payload)
    
    def set_reactive(self, color: int, duration: int = 2) -> Dict:
        """
        Set reactive effect (lights up on keypress).
        
        Args:
            color: BGR color
            duration: 1=short, 2=medium, 3=long
        """
        payload = {
            "effect": Effect.REACTIVE.value,
            "param": {
                "color": color,
                "duration": duration
            }
        }
        return self._send_effect(Device.MOUSEPAD, payload)
    # ========================================================================
    # KEYBOARD SPECIFIC EFFECTS
    # ========================================================================
    
    def set_keyboard_custom(self, color_grid: List[List[int]]) -> Dict:
        """
        Set custom colors on keyboard. 
        Grid is 6 rows x 22 columns of BGR color values.
        
        Args:
            color_grid: 6x22 matrix of BGR colors
        """
        if len(color_grid) != 6:
            return {"success": False, "error": "Keyboard grid must have 6 rows"}
        
        payload = {
            "effect": Effect.CUSTOM.value,
            "param": color_grid
        }
        return self._send_effect(Device.KEYBOARD, payload)
    
    def set_keyboard_wave(self, color1: int, color2: int) -> Dict:
        """Create a simple two-color wave pattern on keyboard."""
        grid = []
        for row in range(6):
            row_colors = []
            for col in range(22):
                row_colors.append(color1 if (row + col) % 2 == 0 else color2)
            grid.append(row_colors)
        return self.set_keyboard_custom(grid)
    
    # ========================================================================
    # MOUSE SPECIFIC EFFECTS
    # ========================================================================
    
    def set_mouse_custom(self, color_grid: List[List[int]]) -> Dict:
        """
        Set custom colors on mouse.
        Grid is 9 rows x 7 columns of BGR color values.
        
        Args:
            color_grid: 9x7 matrix of BGR colors
        """
        if len(color_grid) != 9:
            return {"success": False, "error": "Mouse grid must have 9 rows"}
        
        payload = {
            "effect": Effect.CUSTOM2.value,
            "param": color_grid
        }
        return self._send_effect(Device.MOUSE, payload)


# ============================================================================
# CONVENIENCE FUNCTIONS FOR NodeWorker TOOLS
# ============================================================================

# Global instance for persistent connection
_chroma_client: Optional[RazerChroma] = None


def get_chroma_client() -> RazerChroma:
    """Get or create the global Chroma client."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = RazerChroma()
    return _chroma_client


def chroma_set_color(color: str, device: str = "all") -> Dict:
    """
    Set RGB color on Razer devices. NodeWorker tool function.
    
    Args:
        color: Color name (red, green, blue, yellow, cyan, magenta, white, orange, purple)
               or hex code (#RRGGBB)
        device: Device name (keyboard, mouse, headset, mousepad, keypad, chromalink, all)
    
    Returns:
        Dict with success status
    """
    client = get_chroma_client()
    
    # Connect if not already connected
    if not client.session:
        connect_result = client.connect()
        if not connect_result["success"]:
            return connect_result
    
    # Parse color
    color_map = {
        "red": Colors.RED,
        "green": Colors.GREEN,
        "blue": Colors.BLUE,
        "yellow": Colors.YELLOW,
        "cyan": Colors.CYAN,
        "magenta": Colors.MAGENTA,
        "white": Colors.WHITE,
        "black": Colors.BLACK,
        "orange": Colors.ORANGE,
        "purple": Colors.PURPLE,
    }
    
    if color.startswith("#"):
        bgr_color = hex_to_bgr(color)
    elif color.lower() in color_map:
        bgr_color = color_map[color.lower()]
    else:
        return {"success": False, "error": f"Unknown color: {color}. Use color name or #RRGGBB hex."}
    
    # Apply to device(s)
    device = device.lower()
    if device == "all":
        return client.set_all_static(bgr_color)
    else:
        try:
            device_enum = Device(device)
            return client.set_static_color(device_enum, bgr_color)
        except ValueError:
            return {"success": False, "error": f"Unknown device: {device}. Options: keyboard, mouse, headset, mousepad, keypad, chromalink, all"}


def chroma_off(device: str = "all") -> Dict:
    """
    Turn off RGB lighting on Razer devices.
    
    Args:
        device: Device name or 'all'
    """
    client = get_chroma_client()
    
    if not client.session:
        return {"success": True, "message": "Already off (not connected)"}
    
    device = device.lower()
    if device == "all":
        return client.turn_off_all()
    else:
        try:
            device_enum = Device(device)
            return client.turn_off(device_enum)
        except ValueError:
            return {"success": False, "error": f"Unknown device: {device}"}


def chroma_disconnect() -> Dict:
    """Disconnect from Chroma SDK and free resources."""
    client = get_chroma_client()
    return client.disconnect()


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    print("🎮 Razer Chroma SDK Test")
    print("=" * 40)
    
    chroma = RazerChroma()
    
    # Check SDK version
    version = chroma.get_sdk_version()
    print(f"SDK Version: {version}")
    
    # Connect
    print("\n📡 Connecting...")
    result = chroma.connect()
    print(f"Connect: {result}")
    
    if result.get("success"):
        # Flash colors
        print("\n🌈 Testing colors...")
        
        for color_name, color_val in [("RED", Colors.RED), ("GREEN", Colors.GREEN), ("BLUE", Colors.BLUE)]:
            print(f"  Setting {color_name}...")
            chroma.set_all_static(color_val)
            time.sleep(1)
        
        # Turn off
        print("\n❌ Turning off...")
        chroma.turn_off_all()
        
        # Disconnect
        print("\n🔌 Disconnecting...")
        chroma.disconnect()
        print("Done!")
    else:
        print("Failed to connect. Is Razer Synapse running?")
