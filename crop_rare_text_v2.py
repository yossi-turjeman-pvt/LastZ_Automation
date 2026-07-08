from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/gifts_tabs.png")
# Crop a wider area containing the word "Rare" on the right side
# gifts_tabs.png is 1400 x 200
box = (900, 50, 1300, 180)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/rare_text_clean.png")

print("Cropped clean Rare text template successfully!")
