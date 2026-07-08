from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Shift X to the left and Y slightly down to get the perfect round orange/yellow icon
# Physical range: X=110 to 230, Y=1560 to 1680
box = (110, 1560, 230, 1680)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/orange_badge_icon_clean.png")

print("Cropped orange badge icon template successfully!")
