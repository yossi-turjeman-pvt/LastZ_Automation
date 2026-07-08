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
    time.sleep(0.1)
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.1)
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.1)

# Let's define a grid of coordinates around the detected (950, 375)
# Let's test X values: 930, 950, 970
# Let's test Y values: 360, 375, 390
for x in [930, 950, 970]:
    for y in [360, 375, 390]:
        print(f"Testing click at logical (X={x}, Y={y})...")
        click(x, y)
        time.sleep(0.8) # Wait for potential transition
        
        # Capture screen and crop tab area
        subprocess.run(["screencapture", "-x", f"/tmp/sweep_{x}_{y}.png"])
        im = Image.open(f"/tmp/sweep_{x}_{y}.png")
        # Crop the tab area (physical coordinates: X=800 to 2200, Y=650 to 850)
        cropped = im.crop((800, 650, 2200, 850))
        cropped.save(f"/Users/yossiturjeman/LastZ_Automation/templates/sweep_crop_{x}_{y}.png")
        
        # Reset by clicking Common tab at (640, 375) so we can see if it switches back or not
        # Wait, let's not reset yet, just capture. If one of them succeeds, the tab will stay open on Rare!
print("Sweep completed successfully!")
