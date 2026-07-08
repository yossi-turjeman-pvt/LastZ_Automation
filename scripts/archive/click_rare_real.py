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
    # Move
    move = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, move)
    time.sleep(0.1)
    
    # Down
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.1)
    
    # Up
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.1)

# Click the "Rare" tab at the correct logical coordinates (825, 387)
click(825, 387)
print("Clicked Rare tab at correct coordinates!")

# Wait and capture new screen
time.sleep(2)
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen after clicking Rare tab.")
