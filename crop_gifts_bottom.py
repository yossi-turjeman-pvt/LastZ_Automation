from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop the very bottom area of the Alliance Gifts window
box = (600, 1500, 2400, 1964)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/gifts_bottom.png")
print("Cropped bottom of gifts window successfully!")
