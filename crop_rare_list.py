from PIL import Image

im = Image.open("/tmp/sweep_950_390.png")
# Crop the middle list area where the gifts are listed
box = (1000, 850, 2000, 1650)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/rare_list.png")

print("Cropped middle list area of Rare tab successfully!")
