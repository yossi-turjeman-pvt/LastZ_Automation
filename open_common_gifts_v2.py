import ctypes
import time
import subprocess
from PIL import Image

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

# 1. Close any open profiles
print("Resetting game UI to main base screen...")
click(100, 500)
time.sleep(1.5)

# 2. Open Alliance Menu
print("Opening Alliance menu...")
click(1480, 757)
time.sleep(3.0) # Wait longer for menu to load

# 3. Click Alliance Gifts Button
print("Opening Alliance Gifts window...")
click(887, 650)
time.sleep(3.0) # Wait longer for window to load

# Capture screen
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen successfully!")

# Crop list and bottom area
im = Image.open("/tmp/game_screen.png")
im.crop((1000, 1650, 2000, 1950)).save("/Users/yossiturjeman/LastZ_Automation/templates/common_bottom.png")
im.crop((1000, 850, 2000, 1650)).save("/Users/yossiturjeman/LastZ_Automation/templates/common_list.png")
print("Cropped list and bottom area!")
