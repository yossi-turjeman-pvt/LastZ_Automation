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
    time.sleep(0.2)
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.2)
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.2)

# Set starting state by opening Alliance Menu -> Gifts
print("Setting up starting state (opening Alliance -> Gifts)...")
click(100, 500) # Reset
time.sleep(1.0)
click(1480, 757) # Open Alliance
time.sleep(2.0)
click(887, 650) # Open Gifts
time.sleep(2.0)

# Capture 1: Initial state (Alliance Gifts open)
subprocess.run(["screencapture", "-x", "/tmp/measure_1_initial.png"])
Image.open("/tmp/measure_1_initial.png").crop((1000, 1600, 2000, 1964)).save("/Users/yossiturjeman/LastZ_Automation/templates/measure_crop_1.png")
print("Saved Initial State crop.")

# Perform First Close Click on logical (575, 900)
print("Performing Click 1 on logical (575, 900) to close Alliance Gifts...")
click(575, 900)
time.sleep(3.0)

# Capture 2: State after click 1
subprocess.run(["screencapture", "-x", "/tmp/measure_2_after_click1.png"])
Image.open("/tmp/measure_2_after_click1.png").crop((1000, 1600, 2000, 1964)).save("/Users/yossiturjeman/LastZ_Automation/templates/measure_crop_2.png")
print("Saved crop after Click 1.")

# Perform Second Close Click on logical (612.5, 922.5)
print("Performing Click 2 on logical (612.5, 922.5) to close Alliance Menu...")
click(612.5, 922.5)
time.sleep(3.0)

# Capture 3: State after click 2
subprocess.run(["screencapture", "-x", "/tmp/measure_3_after_click2.png"])
Image.open("/tmp/measure_3_after_click2.png").crop((1000, 1600, 2000, 1964)).save("/Users/yossiturjeman/LastZ_Automation/templates/measure_crop_3.png")
print("Saved crop after Click 2.")

# Perform a safety reset click and capture final state
click(100, 500)
time.sleep(1.0)
subprocess.run(["screencapture", "-x", "/tmp/measure_4_final.png"])
print("Measurement run finished!")
