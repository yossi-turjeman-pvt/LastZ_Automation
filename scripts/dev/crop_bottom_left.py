from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop the bottom-left area of the screen where the orange/yellow icon should be
# Physical width is 3024, height is 1964.
box = (0, 1300, 1000, 1964)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/bottom_left_area.png")

print("Cropped bottom-left area successfully!")
