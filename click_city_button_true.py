import subprocess
import time

# Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

# Click the bottom-left "City/Base" green curved arrow button at logical (25, 925)
print("Clicking bottom-left City/Base green button at (25, 925)...")
subprocess.run(["/Users/yossiturjeman/LastZ_Automation/click_bin", "25", "925"])
time.sleep(4.0) # Wait for city loading transition to finish

# Capture screen to verify
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen!")
