from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop the bottom area of the Battle Rewards modal where the green "Claim All" button is
box = (1200, 1500, 1800, 1700)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/battle_rewards_bottom.png")

print("Cropped Battle Rewards button area successfully!")
