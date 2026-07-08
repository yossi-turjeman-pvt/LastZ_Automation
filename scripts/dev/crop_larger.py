from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Let's crop a larger area on the right side of the screen
# X from 2000 to 3024, Y from 1000 to 1964
box = (2000, 1000, 3024, 1964)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/game_sub_screen.png")
print("Cropped larger sub-screen successfully!")
