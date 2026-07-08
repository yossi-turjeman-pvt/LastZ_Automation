from PIL import Image
import os

results = []
for x in [930, 950, 970]:
    for y in [360, 375, 390]:
        path = f"/Users/yossiturjeman/LastZ_Automation/templates/sweep_crop_{x}_{y}.png"
        if os.path.exists(path):
            im = Image.open(path)
            # Sample Common tab background color at relative (X=340, Y=125) inside the crop
            # sweep_crop is 1400 x 200
            # Common tab center is around relative X = 1280 - 800 = 480 or X = 1140 - 800 = 340
            # Let's sample multiple points inside the Common tab background to find the mean brightness
            pixels = [im.getpixel((340, 125)), im.getpixel((360, 125)), im.getpixel((380, 125))]
            avg_color = sum(sum(p) for p in pixels) / (3.0 * 3.0)
            
            # Let's also sample the Rare tab background at relative (X=1710 - 800 = 910)
            rare_pixels = [im.getpixel((910, 125)), im.getpixel((930, 125)), im.getpixel((950, 125))]
            rare_avg_color = sum(sum(p) for p in rare_pixels) / (3.0 * 3.0)
            
            results.append((x, y, avg_color, rare_avg_color))

# Print results
for x, y, common_b, rare_b in results:
    # Selected/active tab has a very bright white/light background
    # Unselected has a darker gray background
    print(f"Click at ({x}, {y}) -> Common Tab brightness: {common_b:.1f}, Rare Tab brightness: {rare_b:.1f}")
