import subprocess
import time
import pyautogui

# 1. Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

# 2. Click the Alliance icon at (1480, 757) in logical coordinates
# (which correspond to physical x=2960, y=1515 on a 2x Retina screen)
pyautogui.click(1480, 757)
print("Clicked Alliance icon successfully!")

# 3. Wait for popup and capture new screen
time.sleep(1.5)
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured new screen state!")
