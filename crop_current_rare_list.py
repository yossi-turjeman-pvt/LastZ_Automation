from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Crop the middle list area from the current live screenshot
box = (1000, 850, 2000, 1650)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/current_rare_list.png")

print("Cropped current list area successfully!")
