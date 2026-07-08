from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/alliance_menu_bottom.png")
# Let's crop multiple regions of the left side of the bottom bar to find the back arrow circle
# physical X: 1000 to 1300, Y: 150 to 250 (inside the 3024 x 364 crop)
# Let's crop X=1050 to 1150
im.crop((1050, 150, 1150, 250)).save("/Users/yossiturjeman/LastZ_Automation/templates/arrow_test_1050_1150.png")
# Let's crop X=1100 to 1200
im.crop((1100, 150, 1200, 250)).save("/Users/yossiturjeman/LastZ_Automation/templates/arrow_test_1100_1200.png")
# Let's crop X=1150 to 1250
im.crop((1150, 150, 1250, 250)).save("/Users/yossiturjeman/LastZ_Automation/templates/arrow_test_1150_1250.png")

print("Cropped various test regions successfully!")
