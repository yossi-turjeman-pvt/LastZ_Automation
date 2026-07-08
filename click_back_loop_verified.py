import cv2
import numpy as np
import ctypes
import time
import subprocess
import os

# CoreGraphics setup for mouse clicks
cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
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

def is_menu_open():
    screen_path = "/tmp/game_screen.png"
    subprocess.run(["screencapture", "-x", screen_path])
    if not os.path.exists(screen_path):
        return True
        
    img = cv2.imread(screen_path)
    if img is None:
        return True
        
    # Check the pixel color at logical (619.0, 932.5) -> physical (1238, 1865)
    # If it is grey/white (R>100, G>100, B>100), the menu is open!
    color = img[1865, 1238]
    b, g, r = color
    print(f"DEBUG: Color at Menu center = R:{r}, G:{g}, B:{b}")
    return r > 100 and g > 100 and b > 100

print("Draining the menu stack dynamically...")
for i in range(6):
    if is_menu_open():
        print(f"Menu is open. Click {i+1} on logical (575, 900)...")
        click(575, 900)
        time.sleep(2.0) # wait between clicks for animations to settle
    else:
        print("Menu is CLOSED!")
        break

# Safety click top-left sky
click(100, 100)
time.sleep(1.0)

# Capture final screen
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Final screen captured!")
