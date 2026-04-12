"""
Generate QTranslator icon: Blue Q with rocket as the tail/dot.
Outputs: 256x256 PNG and 16x16 ICO, both with transparent background.
"""
from PIL import Image, ImageDraw, ImageFont
import math
import os

def draw_rocket(draw, cx, cy, size, angle_deg):
    """Draw a stylized rocket at position (cx, cy) with given size and rotation angle."""
    angle = math.radians(angle_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    def rotate(px, py):
        rx = cos_a * px - sin_a * py
        ry = sin_a * px + cos_a * py
        return (cx + rx, cy + ry)

    # Rocket body (elongated shape pointing upward before rotation)
    body_h = size * 0.7
    body_w = size * 0.22

    # Nose cone (triangle)
    nose_tip = rotate(0, -body_h * 0.65)
    nose_left = rotate(-body_w * 0.5, -body_h * 0.2)
    nose_right = rotate(body_w * 0.5, -body_h * 0.2)
    draw.polygon([nose_tip, nose_left, nose_right], fill='#FFFFFF')

    # Body (rectangle)
    b_tl = rotate(-body_w * 0.5, -body_h * 0.2)
    b_tr = rotate(body_w * 0.5, -body_h * 0.2)
    b_br = rotate(body_w * 0.5, body_h * 0.25)
    b_bl = rotate(-body_w * 0.5, body_h * 0.25)
    draw.polygon([b_tl, b_tr, b_br, b_bl], fill='#FFFFFF')

    # Window (small circle)
    win_center = rotate(0, -body_h * 0.02)
    win_r = size * 0.06
    draw.ellipse(
        [win_center[0] - win_r, win_center[1] - win_r,
         win_center[0] + win_r, win_center[1] + win_r],
        fill='#1E40AF'
    )

    # Fins (two triangles)
    fin_w = size * 0.18
    fin_h = size * 0.2

    # Left fin
    fl1 = rotate(-body_w * 0.5, body_h * 0.05)
    fl2 = rotate(-body_w * 0.5 - fin_w, body_h * 0.3)
    fl3 = rotate(-body_w * 0.5, body_h * 0.25)
    draw.polygon([fl1, fl2, fl3], fill='#1E40AF')

    # Right fin
    fr1 = rotate(body_w * 0.5, body_h * 0.05)
    fr2 = rotate(body_w * 0.5 + fin_w, body_h * 0.3)
    fr3 = rotate(body_w * 0.5, body_h * 0.25)
    draw.polygon([fr1, fr2, fr3], fill='#1E40AF')

    # Flame (orange-red)
    flame_points = [
        rotate(-body_w * 0.35, body_h * 0.25),
        rotate(0, body_h * 0.55),
        rotate(body_w * 0.35, body_h * 0.25),
    ]
    draw.polygon(flame_points, fill='#F97316')

    # Inner flame (yellow)
    inner_flame = [
        rotate(-body_w * 0.18, body_h * 0.25),
        rotate(0, body_h * 0.42),
        rotate(body_w * 0.18, body_h * 0.25),
    ]
    draw.polygon(inner_flame, fill='#FCD34D')


def generate_icon(size=256):
    """Generate the QTranslator icon at the given size."""
    # We'll work at 4x resolution for anti-aliasing, then downscale
    scale = 4
    s = size * scale
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Q parameters
    center_x = s * 0.47
    center_y = s * 0.44
    outer_r = s * 0.36
    inner_r = s * 0.24
    blue = '#2563EB'
    dark_blue = '#1E40AF'

    # Draw outer circle of Q
    draw.ellipse(
        [center_x - outer_r, center_y - outer_r,
         center_x + outer_r, center_y + outer_r],
        fill=blue
    )

    # Draw inner circle (cut out) of Q
    draw.ellipse(
        [center_x - inner_r, center_y - inner_r,
         center_x + inner_r, center_y + inner_r],
        fill=(0, 0, 0, 0)
    )

    # Q tail - a diagonal bar from bottom-right of the circle
    tail_w = s * 0.1
    tail_angle = math.radians(-40)

    # Starting point at the bottom-right of the Q
    tail_start_x = center_x + outer_r * 0.45
    tail_start_y = center_y + outer_r * 0.55

    # End point extending outward
    tail_len = s * 0.18
    tail_end_x = tail_start_x + tail_len * math.cos(tail_angle)
    tail_end_y = tail_start_y - tail_len * math.sin(tail_angle)

    # Draw tail as a thick line (polygon)
    perp_angle = tail_angle + math.pi / 2
    dx = tail_w * 0.5 * math.cos(perp_angle)
    dy = -tail_w * 0.5 * math.sin(perp_angle)

    tail_poly = [
        (tail_start_x + dx, tail_start_y + dy),
        (tail_start_x - dx, tail_start_y - dy),
        (tail_end_x - dx, tail_end_y - dy),
        (tail_end_x + dx, tail_end_y + dy),
    ]
    draw.polygon(tail_poly, fill=blue)

    # Draw the rocket at the end of the tail, launching upward-right
    rocket_size = s * 0.28
    rocket_cx = tail_end_x + rocket_size * 0.1
    rocket_cy = tail_end_y - rocket_size * 0.05
    draw_rocket(draw, rocket_cx, rocket_cy, rocket_size, angle_deg=-40)

    # Add a subtle gradient/glow effect to the Q by overlaying a lighter ellipse
    glow_r = outer_r * 0.85
    glow_offset_y = -outer_r * 0.15
    # Create a semi-transparent white overlay for the top highlight
    overlay = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.ellipse(
        [center_x - glow_r, center_y + glow_offset_y - glow_r,
         center_x + glow_r, center_y + glow_offset_y + glow_r * 0.6],
        fill=(255, 255, 255, 25)
    )
    img = Image.alpha_composite(img, overlay)

    # Downscale with high-quality resampling for anti-aliasing
    img = img.resize((size, size), Image.LANCZOS)

    return img


def main():
    assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
    os.makedirs(assets_dir, exist_ok=True)

    # Generate 256x256 PNG
    print("Generating 256x256 PNG icon...")
    icon_256 = generate_icon(256)
    png_path = os.path.join(assets_dir, 'icon.png')
    icon_256.save(png_path, 'PNG')
    print(f"Saved: {png_path}")

    # Generate multi-size ICO (includes 16x16 and other common sizes)
    print("Generating ICO icon...")
    ico_path = os.path.join(assets_dir, 'icon.ico')

    # Create multiple sizes for the ICO
    sizes_for_ico = [16, 32, 48, 256]
    ico_images = []
    for sz in sizes_for_ico:
        ico_img = generate_icon(sz)
        ico_images.append(ico_img)

    # Save ICO with all sizes
    ico_images[0].save(
        ico_path,
        format='ICO',
        sizes=[(sz, sz) for sz in sizes_for_ico],
        append_images=ico_images[1:]
    )
    print(f"Saved: {ico_path}")

    # Also save a standalone 16x16 PNG for reference
    icon_16 = generate_icon(16)
    png16_path = os.path.join(assets_dir, 'icon_16.png')
    icon_16.save(png16_path, 'PNG')
    print(f"Saved: {png16_path}")

    print("\nDone! Generated icons:")
    print(f"  - {png_path} (256x256 PNG)")
    print(f"  - {ico_path} (ICO with 16/32/48/256)")
    print(f"  - {png16_path} (16x16 PNG reference)")


if __name__ == '__main__':
    main()
