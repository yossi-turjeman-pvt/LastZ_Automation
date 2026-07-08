from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop center region where game popups usually render
box = (400, 300, 2600, 1600)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_popup.png")
print("Cropped center region successfully!")
