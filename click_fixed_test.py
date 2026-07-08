import ctypes
import time
import subprocess

# Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")

# Define correct signatures (CGPoint struct passed by value!)
void_p = ctypes.c_void_p
uint32 = ctypes.c_uint32
cg.CGEventCreateMouseEvent.argtypes = [void_p, uint32, CGPoint, uint32]
cg.CGEventCreateMouseEvent.restype = void_p
cg.CGEventPost.argtypes = [uint32, void_p]
cg.CGEventPost.restype = None

kCGEventMouseMoved = 5
kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp = 2
kCGHIDEventTap = 0

def click(x, y):
    pt = CGPoint(x, y)
    move = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt, 0)
    cg.CGEventPost(kCGHIDEventTap, move)
    time.sleep(0.15)
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, pt, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.15)
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, pt, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.15)

# Test click on Alliance button at logical (1480, 757)
print("Clicking Alliance button at logical (1480, 757) with correct struct signature...")
click(1480, 757)
time.sleep(2)

# Capture screen to verify
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen!")
