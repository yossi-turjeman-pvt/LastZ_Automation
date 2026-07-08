from PIL import Image

# Open the captured screen
im = Image.open("/tmp/game_screen.png")
width, height = im.size

# Let's crop the right column region where the main menu icons reside
# width is 3024, height is 1964
# X from 2700 to 3024, Y from 1000 to 1964
crop_box = (2700, 1000, 3024, 1964)
cropped_im = im.crop(crop_box)
cropped_im.save("/Users/yossiturjeman/LastZ_Automation/templates/right_column.png")
print("Cropped right column successfully!")
