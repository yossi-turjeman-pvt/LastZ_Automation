import cv2
import os

BASE_DIR = "/Users/yossiturjeman/LastZ_Automation"
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

def extract():
    # Load 5.1.png for the radar/car icon in HQ (middle-left edge, near Arena)
    img_5 = cv2.imread("/Users/yossiturjeman/Downloads/LastZFlow/5.1.png", cv2.IMREAD_GRAYSCALE)
    if img_5 is not None:
        # The user's HQ mode entry button: the "Radar" truck icon on the middle-left
        # Let's crop the truck icon area. Looking at 5.1.png, it's roughly at x: 10-60, y: 700-750
        # Wait, the screenshot 5.1.png shows a little car icon with "Complete 3,600 Radar" under the red skull.
        # But wait! "5.png" has arrows. Let's look at what the user wants to click.
        pass

    # Load 6.1.png for the golden box and "Claim" button on the car screen
    img_6 = cv2.imread("/Users/yossiturjeman/Downloads/LastZFlow/6.1.png", cv2.IMREAD_GRAYSCALE)
    if img_6 is not None:
        # The golden box with "Claim" button is on the right side of the car lane.
        # Let's crop the "Claim" button
        claim_btn = img_6[735:775, 575:635]
        cv2.imwrite(os.path.join(TEMPLATES_DIR, "patrol_claim_btn.png"), claim_btn)
        
        # Also crop the golden chest icon
        golden_chest = img_6[655:725, 575:635]
        cv2.imwrite(os.path.join(TEMPLATES_DIR, "patrol_golden_chest.png"), golden_chest)

    # Load 7.1.png for the "Collect" green button in the Idle Reward modal
    img_7 = cv2.imread("/Users/yossiturjeman/Downloads/LastZFlow/7.1.png", cv2.IMREAD_GRAYSCALE)
    if img_7 is not None:
        # The green "Collect" button is around x: 440-560, y: 740-790
        collect_btn = img_7[740:790, 440:560]
        cv2.imwrite(os.path.join(TEMPLATES_DIR, "patrol_collect_btn.png"), collect_btn)

    print("Templates extracted!")

if __name__ == "__main__":
    extract()
