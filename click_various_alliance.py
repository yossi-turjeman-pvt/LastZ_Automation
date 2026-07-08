import subprocess
import time

# Bring Survival.exe to the front
subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Survival.exe" to true'])
time.sleep(1)

# Click on a dense grid of coordinates around logical (1480, 757) to guarantee we hit the Alliance shield button!
# Let's try X values: 1460, 1470, 1480, 1490
# Let's try Y values: 740, 750, 760, 770
for x in [1460, 1470, 1480, 1490]:
    for y in [740, 750, 760, 770]:
        print(f"Clicking Alliance button at logical (X={x}, Y={y})...")
        subprocess.run(["/Users/yossiturjeman/LastZ_Automation/click_bin", str(x), str(y)])
        time.sleep(0.4)

# Wait for potential open animation
time.sleep(2.0)

# Capture screen to verify
subprocess.run(["screencapture", "-x", "/tmp/game_screen.png"])
print("Captured screen!")
