"""Background removal processing logic."""

import colorsys
import math
import threading
from PIL import Image, ImageFilter


# ─── Color Space Helpers ────────────────────────────────────────────────────

def rgb_to_hsl(r, g, b):
    """Convert RGB (0-255) to HSL (H: 0-360, S: 0-1, L: 0-1)."""
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    h, l, s = colorsys.rgb_to_hls(r_, g_, b_)
    return h * 360, s, l


def hsl_to_rgb(h, s, l):
    """Convert HSL (H: 0-360, S: 0-1, L: 0-1) to RGB (0-255)."""
    r_, g_, b_ = colorsys.hls_to_rgb(h / 360.0, l, s)
    return int(r_ * 255), int(g_ * 255), int(b_ * 255)


def rgb_to_hsv(r, g, b):
    """Convert RGB (0-255) to HSV (H: 0-360, S: 0-1, V: 0-1)."""
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    h, s, v = colorsys.rgb_to_hsv(r_, g_, b_)
    return h * 360, s, v


def hsv_to_rgb(h, s, v):
    """Convert HSV (H: 0-360, S: 0-1, V: 0-1) to RGB (0-255)."""
    r_, g_, b_ = colorsys.hsv_to_rgb(h / 360.0, s, v)
    return int(r_ * 255), int(g_ * 255), int(b_ * 255)


def rgb_to_hsi(r, g, b):
    """Convert RGB (0-255) to HSI (H: 0-360, S: 0-1, I: 0-1)."""
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    i = (r_ + g_ + b_) / 3.0
    if i == 0:
        s = 0
    else:
        s = 1 - min(r_, g_, b_) / i
    num = 0.5 * ((r_ - g_) + (r_ - b_))
    den = ((r_ - g_) ** 2 + (r_ - b_) * (g_ - b_)) ** 0.5
    if den == 0:
        h = 0
    else:
        theta = math.acos(max(-1.0, min(1.0, num / den)))
        h = theta if b_ <= g_ else (2 * math.pi - theta)
        h = math.degrees(h)
    return h, s, i


def hsi_to_rgb(h, s, i):
    """Convert HSI (H: 0-360, S: 0-1, I: 0-1) to RGB (0-255)."""
    h_rad = math.radians(h % 360)
    if h < 120:
        b_ = i * (1 - s)
        r_ = i * (1 + s * math.cos(h_rad) / math.cos(math.radians(60) - h_rad))
        g_ = 3 * i - (r_ + b_)
    elif h < 240:
        h_rad = math.radians(h - 120)
        r_ = i * (1 - s)
        g_ = i * (1 + s * math.cos(h_rad) / math.cos(math.radians(60) - h_rad))
        b_ = 3 * i - (r_ + g_)
    else:
        h_rad = math.radians(h - 240)
        g_ = i * (1 - s)
        b_ = i * (1 + s * math.cos(h_rad) / math.cos(math.radians(60) - h_rad))
        r_ = 3 * i - (g_ + b_)
    return (
        int(max(0, min(255, r_ * 255))),
        int(max(0, min(255, g_ * 255))),
        int(max(0, min(255, b_ * 255))),
    )


# ─── Processing Functions ───────────────────────────────────────────────────

def color_distance(c1, c2):
    """Euclidean distance between two RGB tuples."""
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def create_magic_wand_mask(image, seed_point, threshold, cancel_event=None):
    """
    Flood-fill style mask from seed_point within threshold.
    Returns a grayscale Image (mode 'L') where 255 = selected.
    If cancel_event is set, aborts early and returns partial mask.
    """
    width, height = image.size
    pixels = image.load()
    sx, sy = seed_point
    if sx < 0 or sx >= width or sy < 0 or sy >= height:
        return Image.new("L", image.size, 0)

    seed_color = pixels[sx, sy][:3]
    mask = Image.new("L", image.size, 0)
    mask_pixels = mask.load()

    visited = set()
    queue = [(sx, sy)]
    visited.add((sx, sy))

    while queue:
        if cancel_event and cancel_event.is_set():
            return None  # Cancelled

        x, y = queue.pop()
        px_color = pixels[x, y][:3]
        if color_distance(seed_color, px_color) <= threshold:
            mask_pixels[x, y] = 255
            for nx, ny in [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]:
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((nx, ny))

    return mask


def dilate_mask(mask, amount):
    """Dilate a mask by amount pixels using MaxFilter."""
    if amount <= 0:
        return mask
    result = mask
    for _ in range(amount):
        result = result.filter(ImageFilter.MaxFilter(3))
    return result


def process_background_removal(image, points, global_threshold, color_space,
                               cancel_event=None):
    """
    Process background removal.
    - points: list of dicts {x, y, threshold, feathering}
    - global_threshold: overall threshold for deciding full-transparent vs partial
    - color_space: 'HSL', 'HSV', or 'HSI'
    - cancel_event: threading.Event, if set the processing aborts and returns None
    Returns RGBA Image with background removed, or None if cancelled.
    """
    if not points:
        return image.convert("RGBA")

    width, height = image.size
    rgb_image = image.convert("RGB")

    # Build combined mask from all points
    combined_mask = Image.new("L", (width, height), 0)

    for pt in points:
        if cancel_event and cancel_event.is_set():
            return None

        pt_mask = create_magic_wand_mask(
            rgb_image, (pt["x"], pt["y"]), pt["threshold"], cancel_event
        )
        if pt_mask is None:
            return None  # Cancelled

        pt_mask = dilate_mask(pt_mask, pt["feathering"])
        combined_mask = Image.composite(
            Image.new("L", (width, height), 255),
            combined_mask,
            pt_mask,
        )

    if cancel_event and cancel_event.is_set():
        return None

    # Process pixels covered by the combined mask
    result = rgb_image.copy().convert("RGBA")
    result_pixels = result.load()
    mask_pixels = combined_mask.load()
    src_pixels = rgb_image.load()

    # Choose color space functions
    if color_space == "HSL":
        to_cs = rgb_to_hsl
        from_cs = hsl_to_rgb
    elif color_space == "HSV":
        to_cs = rgb_to_hsv
        from_cs = hsv_to_rgb
    else:  # HSI
        to_cs = rgb_to_hsi
        from_cs = hsi_to_rgb
    lightness_idx = 2

    for y in range(height):
        # Check cancellation every row for responsiveness
        if cancel_event and cancel_event.is_set():
            return None

        for x in range(width):
            if mask_pixels[x, y] == 0:
                continue

            r, g, b = src_pixels[x, y]
            min_dist = float("inf")
            for pt in points:
                px, py = pt["x"], pt["y"]
                if 0 <= px < width and 0 <= py < height:
                    seed_color = src_pixels[px, py]
                    dist = color_distance((r, g, b), seed_color)
                    min_dist = min(min_dist, dist)

            if min_dist <= global_threshold:
                result_pixels[x, y] = (0, 0, 0, 0)
            else:
                h, s, lightness = to_cs(r, g, b)
                alpha = int((1.0 - lightness) * 255)
                cs_values = [h, s, lightness]
                cs_values[lightness_idx] = 0
                new_r, new_g, new_b = from_cs(*cs_values)
                result_pixels[x, y] = (new_r, new_g, new_b, alpha)

    return result
