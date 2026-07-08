import cv2
import numpy as np
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
    move = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, move)
    time.sleep(0.15)
    down = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.15)
    up = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, x, y, 0)
    cg.CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.15)

# Load the clean green claim button template
template_path = "/Users/yossiturjeman/LastZ_Automation/templates/claim_button_clean.png"
template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
h, w = template.shape

max_attempts = 15
claimed_count = 0

for attempt in range(max_attempts):
    # 1. Capture screen
    screen_path = "/tmp/game_screen.png"
    subprocess.run(["screencapture", "-x", screen_path])
    
    # 2. Load screen in grayscale
    large_img = cv2.imread(screen_path, cv2.IMREAD_GRAYSCALE)
    
    # 3. Perform template matching
    res = cv2.matchTemplate(large_img, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    
    print(f"Attempt {attempt+1}: Max similarity of claim button = {max_val:.4f}")
    
    # 4. If high similarity match is found, click it!
    if max_val > 0.85:
        top_left = max_loc
        center_x = top_left[0] + w // 2
        center_y = top_left[1] + h // 2
        
        logical_x = center_x / 2
        logical_y = center_y / 2
        
        print(f"-> Found claim button at physical ({center_x}, {center_y}) -> logical ({logical_x:.1f}, {logical_y:.1f}). Clicking...")
        click(logical_x, logical_y)
        claimed_count += 1
        time.sleep(1.2) # Wait for animation and UI state update
    else:
        print("-> No more claim buttons found with high confidence!")
        break

print(f"Finished claiming rare gifts! Total claimed this run: {claimed_count}")
