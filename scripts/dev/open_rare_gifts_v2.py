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
    time.sleep(0.2)
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.2)
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.2)

# Click the title bar first to ensure window is 100% active and responsive
print("Focusing window title bar...")
click(756, 45)
time.sleep(1)

# Step 1: Click Alliance Shield
print("Clicking Alliance Shield...")
click(1480, 757)
time.sleep(2)

# Step 2: Click Alliance Gifts
print("Clicking Alliance Gifts...")
click(887, 650)
time.sleep(2)

# Step 3: Click Rare Tab (Let's click twice to make sure it opens)
print("Clicking Rare Tab...")
click(875, 387)
time.sleep(0.5)
click(875, 387)
time.sleep(3) # Wait longer for redraw

# Step 4: Capture screen
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen successfully!")
