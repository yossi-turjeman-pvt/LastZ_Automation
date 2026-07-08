from PIL import Image

im = Image.open("/tmp/sweep_950_390.png")
# Let's crop a vertically lower box to see the actual bottom bar of the window
box = (1000, 1650, 2000, 1950)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/rare_bottom.png")

print("Cropped bottom area of Rare tab successfully!")
