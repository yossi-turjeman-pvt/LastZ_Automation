from PIL import Image

def find_template(large_image_path, template_image_path, threshold=20):
    large_img = Image.open(large_image_path).convert("RGB")
    template_img = Image.open(template_image_path).convert("RGB")
    
    lw, lh = large_img.size
    tw, th = template_img.size
    
    print(f"Searching for template ({tw}x{th}) inside large image ({lw}x{lh})...")
    
    # Simple template matching by sampling a few key pixels from the template to make it fast
    # Let's sample 5 representative pixels from the template
    samples = [
        (tw // 2, th // 2), # center
        (tw // 4, th // 4), # top-left
        (3 * tw // 4, th // 4), # top-right
        (tw // 4, 3 * th // 4), # bottom-left
        (3 * tw // 4, 3 * th // 4) # bottom-right
    ]
    sample_colors = [template_img.getpixel(pos) for pos in samples]
    
    best_match = None
    min_diff = 999999
    
    # Scan the right side of the screen where the alliance button lives (X > 2500, Y > 1000)
    for y in range(1200, lh - th, 2):
        for x in range(2500, lw - tw, 2):
            diff = 0
            for (tx, ty), tc in zip(samples, sample_colors):
                rc, gc, bc = large_img.getpixel((x + tx, y + ty))[:3]
                diff += abs(rc - tc[0]) + abs(gc - tc[1]) + abs(bc - tc[2])
            
            if diff < min_diff:
                min_diff = diff
                best_match = (x, y)
                
            if diff < threshold:
                print(f"Match found at physical coordinates: ({x}, {y}) with diff {diff}")
                return x + tw // 2, y + th // 2
                
    print(f"No perfect match. Best candidate at physical ({best_match[0]}, {best_match[1]}) with diff {min_diff}")
    return best_match[0] + tw // 2, best_match[1] + th // 2

# Test find_template on the alliance shield
x_phys, y_phys = find_template("/tmp/game_screen.png", "/Users/yossiturjeman/LastZ_Automation/templates/alliance_shield_clean.png")
print(f"Calculated center in physical: ({x_phys}, {y_phys})")
print(f"Logical coordinates (Retina 2x): ({x_phys / 2}, {y_phys / 2})")
