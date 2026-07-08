from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/alliance_popup.png")

# Let's shift X to the right and Y down to capture the Alliance Gifts button
# X offset: 1100 to 1650, Y offset: 900 to 1100 (relative to alliance_popup.png which starts at X=400, Y=300)
# So physical box: X from 1500 to 2050, Y from 1200 to 1400
box = (1100, 900, 1650, 1100)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_gifts_precise.png")

print("Alliance Gifts button precisely cropped!")
