from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/battle_rewards_bottom.png")
# Crop ONLY the green button, excluding background
# battle_rewards_bottom.png is 600 x 200
box = (140, 50, 460, 150)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/universal_claim_all_button.png")

print("Cropped universal green Claim All button template successfully!")
