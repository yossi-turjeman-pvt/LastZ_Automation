import cv2
import numpy as np
import ctypes
import time
import subprocess
import os
import sys
import datetime

# Absolute path injection to guarantee pyenv 3.10 compatibility
USER_PYTHON_PACKAGES = "/Users/yossiturjeman/Library/Python/3.9/lib/python/site-packages"
if USER_PYTHON_PACKAGES not in sys.path:
    sys.path.insert(0, USER_PYTHON_PACKAGES)

BASE_DIR = "/Users/yossiturjeman/LastZ_Automation"
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
VERIFICATION_LOG = os.path.join(BASE_DIR, "verification_results.txt")

# CoreGraphics click setup
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

def focus_game():
    subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
    time.sleep(1.5)

def log_verification(msg):
    print(msg)
    with open(VERIFICATION_LOG, "a") as f:
        f.write(msg + chr(10))

# Import the claim flow functions directly
sys.path.append(BASE_DIR)
import alliance_gifts_auto

def verify_step_state(screen_path):
    img = cv2.imread(screen_path)
    if img is None:
        return "UNKNOWN (No Image)"
        
    # Let's check the pixel color at physical X=1225, Y=1845 (logical 612.5, 922.5)
    # If the Alliance Menu is open, this is the circular Back button which is grey/white
    color = img[1845, 1225] # BGR format
    b, g, r = color
    
    # Check if Gifts modal is open by checking the header color at physical X=1512, Y=150 (logical 756, 75)
    # Gifts modal header has a very distinct dark/gold banner background
    gifts_header_color = img[150, 1512]
    gh_b, gh_g, gh_r = gifts_header_color
    
    if gh_r > 150 and gh_g > 120 and gh_b < 100: # Gold/brown banner of Gifts modal
        return "ALLIANCE_GIFTS_OPEN"
    elif r > 100 and g > 100 and b > 100: # Grey/white back button of Alliance Menu
        return "ALLIANCE_MENU_OPEN"
    else:
        return "MAIN_BASE_MAP_CLEAN"

def run_full_claim_and_verify(run_id):
    log_verification(f"=================== RUN {run_id} START ===================")
    focus_game()
    
    # Step 1: Self-correcting reset
    log_verification("Step 1: Resetting UI by clicking outside...")
    click(100, 300) # Close Gifts if open
    time.sleep(1.5)
    click(100, 300) # Close Alliance if open
    time.sleep(1.5)
    click(100, 300) # Close any potential March popups
    time.sleep(1.0)
    
    # Verify starting state is clean map
    init_screen = f"/tmp/verify_run_{run_id}_step1_init.png"
    subprocess.run(["screencapture", "-x", init_screen])
    state = verify_step_state(init_screen)
    log_verification(f"-> Verified Starting State: {state}")
    
    # Step 2: Open Alliance Menu
    log_verification("Step 2: Opening Alliance Menu...")
    click(1480, 757)
    time.sleep(2.5)
    
    # Verify Alliance Menu is open
    alliance_screen = f"/tmp/verify_run_{run_id}_step2_alliance.png"
    subprocess.run(["screencapture", "-x", alliance_screen])
    state = verify_step_state(alliance_screen)
    log_verification(f"-> Verified Alliance Menu State: {state}")
    
    # Step 3: Open Alliance Gifts Window
    log_verification("Step 3: Opening Alliance Gifts...")
    click(887, 650)
    time.sleep(2.5)
    
    # Verify Alliance Gifts is open
    gifts_screen = f"/tmp/verify_run_{run_id}_step3_gifts.png"
    subprocess.run(["screencapture", "-x", gifts_screen])
    state = verify_step_state(gifts_screen)
    log_verification(f"-> Verified Alliance Gifts State: {state}")
    
    # Step 4: Claim all Common & Rare gifts
    log_verification("Step 4: Processing Claiming Loop...")
    common_status = alliance_gifts_auto.claim_gifts_with_templates(is_common=True)
    log_verification(f"-> Common Tab: {common_status}")
    
    # Switch to Rare Tab
    click(950, 390)
    time.sleep(2.0)
    rare_status = alliance_gifts_auto.claim_gifts_with_templates(is_common=False)
    log_verification(f"-> Rare Tab: {rare_status}")
    
    # Step 5: Close Alliance Gifts modal by clicking outside
    log_verification("Step 5: Closing Alliance Gifts sub-window by clicking outside...")
    click(100, 300)
    time.sleep(3.0)
    
    # Verify Alliance Gifts closed, Alliance Menu remains open
    after_gifts_screen = f"/tmp/verify_run_{run_id}_step5_after_gifts.png"
    subprocess.run(["screencapture", "-x", after_gifts_screen])
    state = verify_step_state(after_gifts_screen)
    log_verification(f"-> Verified Post-Gifts Window State: {state}")
    
    # Step 6: Close Alliance Menu window by clicking outside
    log_verification("Step 6: Closing Alliance Menu window by clicking outside...")
    click(100, 300)
    time.sleep(3.0)
    
    # Verify everything is closed and main map is visible
    final_screen = f"/tmp/verify_run_{run_id}_step6_final.png"
    subprocess.run(["screencapture", "-x", final_screen])
    state = verify_step_state(final_screen)
    log_verification(f"-> Verified Final State: {state}")
    log_verification(f"=================== RUN {run_id} COMPLETE ===================")
    
    # Clean up screenshots to ensure zero disk overhead
    for path in [init_screen, alliance_screen, gifts_screen, after_gifts_screen, final_screen]:
        if os.path.exists(path):
            os.remove(path)

def start_verification_suite():
    # Reset log file
    with open(VERIFICATION_LOG, "w") as f:
        f.write("=== LASTZ AUTOMATION THREE-RUN VERIFICATION REPORT ===" + chr(10))
        f.write(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + chr(10) + chr(10))
        
    log_verification("Launching 3 consecutive test runs with active state verification...")
    
    for i in range(1, 4):
        run_full_claim_and_verify(i)
        time.sleep(3.0) # Rest between runs
        
    log_verification("Verification suite finished! Read verification_results.txt for full detailed metrics.")

if __name__ == "__main__":
    start_verification_suite()
