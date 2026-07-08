import ctypes
import time
import subprocess

# 1. Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

# 2. Click using CoreGraphics via ctypes (perfect for bypassing pyobjc issues)
# Define types
double = ctypes.c_double
uint32 = ctypes.c_uint32
void_p = ctypes.c_void_p

cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")

# Function signatures
cg.CGEventCreateMouseEvent.argtypes = [void_p, uint32, double, double, uint32]
cg.CGEventCreateMouseEvent.restype = void_p

cg.CGEventPost.argtypes = [uint32, void_p]
cg.CGEventPost.restype = None

# Constants
kCGEventMouseMoved = 5
kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp = 2
kCGHIDEventTap = 0

def click(x, y):
    # Mouse Move
    move = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, move)
    time.sleep(0.1)
    
    # Mouse Down
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.1)
    
    # Mouse Up
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.1)

# Click the Alliance icon
click(1480, 757)
print("Clicked Alliance button successfully using CoreGraphics!")

# Wait and capture new screen
time.sleep(2)
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen after click.")
