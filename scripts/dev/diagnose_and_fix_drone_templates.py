"""
Diagnose drone-gift template scale and fix it.

Run this with the game visible on screen.  It will:
  1. Capture a live Retina screenshot and report its dimensions
  2. Test each drone template at ORIGINAL scale and report confidence
  3. Scale every drone template up by retina_scale (2.0)
  4. Test again at the corrected scale and report confidence
  5. Save the fixed templates to templates/active/ if all 4 pass a minimum bar

Usage:
    cd /Users/yossiturjeman/LastZ_Automation
    python3 scripts/dev/diagnose_and_fix_drone_templates.py
"""
import os
import sys
import subprocess
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lastz.config import PROJECT_ROOT, retina_scale

TEMPLATES_DIR = PROJECT_ROOT / "templates" / "active"
SCREEN_PATH = "/tmp/lastz_diag_screen.png"
DRONE_TEMPLATES = [
    "hq_world_button.png",
    "hq_drone_gift_chest.png",
    "drone_claim_btn.png",
    "drone_collect_btn.png",
]

def capture_screen() -> np.ndarray:
    subprocess.run(["screencapture", "-x", SCREEN_PATH], check=True)
    img = cv2.imread(SCREEN_PATH, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError("screencapture returned no image")
    return img


def best_confidence(screen: np.ndarray, tpl: np.ndarray) -> float:
    th, tw = tpl.shape
    sh, sw = screen.shape
    if th > sh or tw > sw:
        return 0.0
    result = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1])


def scale_template(tpl: np.ndarray, scale: float) -> np.ndarray:
    h, w = tpl.shape
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(tpl, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)


def main() -> None:
    # Correct scale = (game_logical_width / source_image_width) * retina_scale
    SOURCE_WIDTH = 1024
    GAME_LOGICAL_WIDTH = 1512  # measured via osascript (Survival.exe window width)
    retina = retina_scale()
    scale = (GAME_LOGICAL_WIDTH / SOURCE_WIDTH) * retina
    print(f"\nCorrect scale: {scale:.4f}x  "
          f"(game_logical={GAME_LOGICAL_WIDTH} / source={SOURCE_WIDTH} * retina={retina})\n")

    print("Capturing live screenshot...")
    screen = capture_screen()
    print(f"Screenshot dimensions: {screen.shape[1]}x{screen.shape[0]} (physical pixels)\n")

    print(f"{'Template':<35} {'Original size':>15}  {'Conf @1x':>10}  {'Scaled size':>14}  {'Conf @2x':>10}")
    print("-" * 95)

    all_pass = True
    for name in DRONE_TEMPLATES:
        path = TEMPLATES_DIR / name
        tpl_orig = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if tpl_orig is None:
            print(f"  {name}: FILE NOT FOUND")
            all_pass = False
            continue

        oh, ow = tpl_orig.shape
        conf_1x = best_confidence(screen, tpl_orig)

        tpl_scaled = scale_template(tpl_orig, scale)
        sh_s, sw_s = tpl_scaled.shape
        conf_2x = best_confidence(screen, tpl_scaled)

        flag_1x = "OK" if conf_1x >= 0.50 else "LOW"
        flag_2x = "OK" if conf_2x >= 0.50 else "LOW"
        print(f"  {name:<33} {ow}x{oh:>4}  {conf_1x:>9.4f} {flag_1x}  "
              f"{sw_s}x{sh_s:>4}  {conf_2x:>9.4f} {flag_2x}")

    # Save corrected (2x) templates
    print("\n--- Saving 2x-scaled templates to templates/active/ ---\n")
    for name in DRONE_TEMPLATES:
        path = TEMPLATES_DIR / name
        tpl_orig = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if tpl_orig is None:
            continue
        tpl_scaled = scale_template(tpl_orig, scale)
        cv2.imwrite(str(path), tpl_scaled)
        oh, ow = tpl_orig.shape
        sh_s, sw_s = tpl_scaled.shape
        print(f"  {name}: {ow}x{oh} -> {sw_s}x{sh_s}")

    # Verify after saving
    print("\n--- Verification pass (confidence after fix) ---\n")
    for name in DRONE_TEMPLATES:
        path = TEMPLATES_DIR / name
        tpl = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            print(f"  {name}: FILE NOT FOUND")
            all_pass = False
            continue
        th, tw = tpl.shape
        conf = best_confidence(screen, tpl)
        status = "PASS" if conf >= 0.40 else "WARN (low — may need live recapture)"
        print(f"  {name}: {tw}x{th}  conf={conf:.4f}  {status}")
        if conf < 0.40:
            all_pass = False

    if os.path.exists(SCREEN_PATH):
        os.remove(SCREEN_PATH)

    print()
    if all_pass:
        print("All templates verified. The drone gift flow should now work.")
    else:
        print("Some templates have low confidence.")
        print("This usually means the template was created from a different")
        print("game window size or resolution than the live display.")
        print("To recapture from the live game, run:")
        print("  screencapture -x /tmp/ref.png")
        print("Then open scripts/dev/extract_drone_gift_templates.py,")
        print("update the crop boxes, and re-run this script.")


if __name__ == "__main__":
    main()
