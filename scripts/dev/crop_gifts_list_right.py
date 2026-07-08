from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Let's crop the right-hand side of the gifts list area (physical coordinates)
# X from 1200 to 2200, Y from 1200 to 1800
box = (1200, 1200, 2200, 1800)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/gifts_list_right.png")
print("Cropped right side of gifts list successfully!")
