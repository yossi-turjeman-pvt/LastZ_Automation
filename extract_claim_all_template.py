from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/common_bottom.png")
# Crop "Claim All" button excluding the red notification badge on the right
# common_bottom.png is 1000 x 300
box = (350, 80, 650, 190)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/claim_all_button_clean.png")

print("Cropped clean Claim All button template successfully!")
