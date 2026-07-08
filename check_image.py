from PIL import Image

im = Image.open("/tmp/game_screen.png")
colors = im.getcolors(maxcolors=100)
if colors is not None:
    print("Found unique colors:", len(colors))
else:
    print("Image has more than 100 unique colors (likely non-black!)")
