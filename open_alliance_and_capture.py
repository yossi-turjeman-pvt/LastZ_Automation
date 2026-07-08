import ctypes
import time
import subprocess
from PIL import Image

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

# Reset UI first
print("Resetting game UI...")
click(100, 500)
time.sleep(1.0)

# Open Alliance Menu
print("Opening Alliance menu...")
click(1480, 757)
time.sleep(2.5)

# Capture screen
subprocess.run(["screencapture", "-x", "/tmp/alliance_menu_screen.png"])
print("Captured screen!")

# Crop top bar and bottom bar to locate close buttons
im = Image.open("/tmp/alliance_menu_screen.png")
# Physical width is 3024, height is 1964.
# Crop top bar (Y = 0 to 300)
im.crop((0, 0, 3024, 300)).save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_menu_top.png")
# Crop bottom bar (Y = 1600 to 1964)
im.crop((0, 1600, 3024, 1964)).save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_menu_bottom.png")
print("Cropped Alliance Menu top and bottom regions!")
