from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/alliance_gifts_precise.png")
# Crop out the gold-and-black chest icon (size 550 x 200)
# Let's crop 120x120 around X=40 to 160, Y=40 to 160
box = (40, 40, 160, 160)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_gifts_chest.png")

print("Alliance Gifts chest template cropped successfully!")
