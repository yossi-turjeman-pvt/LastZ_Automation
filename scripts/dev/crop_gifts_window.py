from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop a large central area for the Alliance Gifts sub-window
box = (400, 150, 2600, 1800)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/gifts_window.png")
print("Cropped Alliance Gifts window successfully!")
