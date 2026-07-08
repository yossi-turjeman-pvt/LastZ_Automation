from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/rare_list.png")
# Crop the first green "Claim" button
# Size: width=190, height=80, starting at X=690, Y=110 relative to rare_list.png
box = (690, 110, 880, 190)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/claim_button_clean.png")

print("Cropped clean green Claim button template successfully!")
