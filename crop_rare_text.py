from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/gifts_tabs.png")
# Crop the word "Rare"
# gifts_tabs.png is 1400 x 200
# "Rare" word is centered around X_offset = 850, Y_offset = 125
box = (780, 80, 920, 170)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/rare_text_clean.png")

print("Cropped clean Rare text template successfully!")
