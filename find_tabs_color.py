from PIL import Image

im = Image.open("/tmp/game_screen.png")
width, height = im.size

# Scan Y=775 (physical Y) across X=1000 to 2000 (physical X)
# Let's print the colors and find the boundaries of the white "Common" tab vs grey "Rare" tab
for x in range(1000, 2000, 20):
    r, g, b = im.getpixel((x, 775))[:3]
    # White active tab has high values (e.g., > 240)
    # Grey inactive tab has lower values (e.g., around 180-210)
    print(f"X={x:4d}: RGB=({r:3d}, {g:3d}, {b:3d})")
