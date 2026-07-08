import ctypes
import time
import subprocess

# Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1.5)

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

print("Focusing game...")
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1.5)

# 1. Open Alliance Menu
print("Opening Alliance Menu at logical (1480, 757)...")
click(1480, 757)
time.sleep(2.5)

# Capture screenshot with Alliance open
screenshot_path_open = "/Users/yossiturjeman/LastZ_Automation/after_outside_click_open.png"
subprocess.run(["screencapture", "-x", screenshot_path_open])
print(f"Captured screen with Alliance open to {screenshot_path_open}")

# 2. Click outside the modal to close it
print("Clicking outside the modal at (100, 300) to go back/close...")
click(100, 300)
time.sleep(2.5)

# Capture screenshot after close click
screenshot_path_closed = "/Users/yossiturjeman/LastZ_Automation/after_outside_click_closed.png"
subprocess.run(["screencapture", "-x", screenshot_path_closed])
print(f"Captured screen after close click to {screenshot_path_closed}")
