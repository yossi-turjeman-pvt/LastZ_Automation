"""One-shot VERIFY: click Quit modal Cancel, then capture after. No focus."""
import time
from pathlib import Path

import cv2

from lastz.input import click
from lastz.screen import capture_color, cleanup_temp, physical_to_logical

OUT = Path("logs/debug/verify")
PHYS_X, PHYS_Y = 1853.5, 865.5  # Cancel center from cancel_01_before.png


def main() -> None:
    before = capture_color()
    cv2.imwrite(str(OUT / "cancel_01_before_recheck.png"), before)
    lx, ly = physical_to_logical(PHYS_X, PHYS_Y)
    print(f"Click Cancel logical ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(1.2)
    after = capture_color()
    path = OUT / "cancel_01_after.png"
    cv2.imwrite(str(path), after)
    print(f"saved {path} {after.shape}")
    cleanup_temp()


if __name__ == "__main__":
    main()
