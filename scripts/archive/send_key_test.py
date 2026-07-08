import subprocess
import time

# Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

# Test sending different key presses (Space, C, H, Tab) with a short delay in between to see which one switches the view!
keys = ["space", "c", "h", "tab"]
for k in keys:
    print(f"Sending key '{k}' to Survival.exe...")
    subprocess.run(["osascript", "-e", f'tell application "System Events" to keystroke "{k}"'])
    time.sleep(2.0)
    
    # Capture screen to see if it switched
    subprocess.run(["screencapture", "-x", f"/tmp/key_test_{k}.png"])
    print(f"Captured screen for key '{k}'!")
