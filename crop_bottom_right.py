from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop bottom right menu area
# Width: 3024, Height: 1964
box = (2820, 1300, 3024, 1900)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/bottom_right_menu.png")
print("Cropped bottom right menu successfully!")
