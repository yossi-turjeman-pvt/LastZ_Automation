from PIL import Image

im = Image.open("/tmp/game_screen.png")
# Convert to grayscale to simplify thresholding
gray = im.convert("L")
bbox = gray.getbbox()
print("Non-black bounding box:", bbox)
