import ctypes
import time
import subprocess

# Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")

# Define signatures
double = ctypes.c_double
uint32 = ctypes.c_uint32
void_p = ctypes.c_void_p
cg.CGEventCreateMouseEvent.argtypes = [void_p, uint32, double, double, uint32]
cg.CGEventCreateMouseEvent.restype = void_p
cg.CGEventPost.argtypes = [uint32, void_p]
cg.CGEventPost.restype = None

kCGEventMouseMoved = 5
kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp = 2
kCGHIDEventTap = 0

def click(x, y):
    move = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, move)
    time.sleep(0.15)
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.15)
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.15)

# Set starting state by opening Alliance Menu -> Gifts
print("Setting up starting state (opening Alliance -> Gifts)...")
click(100, 500) # Reset
time.sleep(1.0)
click(1480, 757) # Open Alliance
time.sleep(2.0)
click(887, 650) # Open Gifts
time.sleep(2.0)

# Click 1: Close Alliance Gifts modal using its exact Back button coordinate: (646.5, 936.0)
print("Clicking Alliance Gifts Back button at exact coordinate (646.5, 936.0)...")
click(646.5, 936.0)
time.sleep(3.0)

# Click 2: Close Alliance Menu window using its exact Back button coordinate: (619.0, 932.5)
print("Clicking Alliance Menu Back button at exact coordinate (619.0, 932.5)...")
click(619.0, 932.5)
time.sleep(3.0)

# Final safety click
click(100, 500)
time.sleep(1.0)

# Capture screen to verify
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen!")
