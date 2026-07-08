from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop the orange badge icon from the bottom-left background
# Physical range: X=180 to 300, Y=1530 to 1650
box = (180, 1530, 300, 1650)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/orange_badge_icon_clean.png")

print("Cropped orange badge icon template successfully!")
