from PIL import Image
import os

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/right_column.png")
width, height = im.size

# slice into vertical blocks of 100 pixels
os.makedirs("/Users/yossiturjeman/LastZ_Automation/slices", exist_ok=True)
for i in range(0, height, 100):
    box = (0, i, width, min(i+100, height))
    slice_im = im.crop(box)
    slice_im.save(f"/Users/yossiturjeman/LastZ_Automation/slices/slice_{i}.png")

print("Sliced right column into 100px slices successfully!")
