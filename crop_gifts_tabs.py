from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/gifts_window.png")
# Crop the tabs area of the gifts window
# gifts_window.png starts at X=400, Y=150
box = (400, 500, 1800, 700)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/gifts_tabs.png")
print("Cropped gifts tabs successfully!")
