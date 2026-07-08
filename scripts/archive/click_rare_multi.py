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

def click_and_drag(x, y):
    # 1. Move mouse to target
    move = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, move)
    time.sleep(0.15)
    
    # 2. Left Mouse Down
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.15)
    
    # 3. Left Mouse Up
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.15)

# Let's try multiple logical Y-coordinates around 387 to make sure we hit the tab perfectly!
# The tab is tall, so Y=375, 387, 400 are all safe. Let's do a few clicks!
coords = [(625, 387), (625, 375), (625, 400)]
for x, y in coords:
    print(f"Clicking at logical coordinate: ({x}, {y})")
    click_and_drag(x, y)
    time.sleep(0.5)

# Wait and capture new screen
time.sleep(1.5)
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen after multi-click on Rare tab.")
