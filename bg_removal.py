"""Background removal processing logic using numpy for vectorized operations."""

import numpy as np
from PIL import Image


# ─── Vectorized Color Space Conversions ─────────────────────────────────────

def rgb_array_to_hsl(rgb):
    """
    Convert RGB array (H, W, 3) uint8 to HSL array (H, W, 3) float64.
    Output: H in [0, 360], S in [0, 1], L in [0, 1].
    """
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0

    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    # Lightness
    l = (cmax + cmin) / 2.0

    # Saturation
    s = np.zeros_like(l)
    mask = delta > 0
    low = l <= 0.5
    s[mask & low] = delta[mask & low] / (2.0 * l[mask & low])
    s[mask & ~low] = delta[mask & ~low] / (2.0 - 2.0 * l[mask & ~low])

    # Hue
    h = np.zeros_like(l)
    mask_r = mask & (cmax == r)
    mask_g = mask & (cmax == g) & ~mask_r
    mask_b = mask & (cmax == b) & ~mask_r & ~mask_g

    h[mask_r] = 60.0 * (((g[mask_r] - b[mask_r]) / delta[mask_r]) % 6)
    h[mask_g] = 60.0 * ((b[mask_g] - r[mask_g]) / delta[mask_g] + 2)
    h[mask_b] = 60.0 * ((r[mask_b] - g[mask_b]) / delta[mask_b] + 4)

    hsl = np.stack([h, s, l], axis=-1)
    return hsl


def hsl_array_to_rgb(hsl):
    """
    Convert HSL array (H, W, 3) float64 to RGB array (H, W, 3) uint8.
    Input: H in [0, 360], S in [0, 1], L in [0, 1].
    """
    h, s, l = hsl[..., 0], hsl[..., 1], hsl[..., 2]

    c = (1 - np.abs(2 * l - 1)) * s
    h_prime = h / 60.0
    x = c * (1 - np.abs(h_prime % 2 - 1))
    m = l - c / 2.0

    r1 = np.zeros_like(h)
    g1 = np.zeros_like(h)
    b1 = np.zeros_like(h)

    # Sector 0: 0 <= h' < 1
    mask = (h_prime >= 0) & (h_prime < 1)
    r1[mask], g1[mask], b1[mask] = c[mask], x[mask], 0
    # Sector 1: 1 <= h' < 2
    mask = (h_prime >= 1) & (h_prime < 2)
    r1[mask], g1[mask], b1[mask] = x[mask], c[mask], 0
    # Sector 2: 2 <= h' < 3
    mask = (h_prime >= 2) & (h_prime < 3)
    r1[mask], g1[mask], b1[mask] = 0, c[mask], x[mask]
    # Sector 3: 3 <= h' < 4
    mask = (h_prime >= 3) & (h_prime < 4)
    r1[mask], g1[mask], b1[mask] = 0, x[mask], c[mask]
    # Sector 4: 4 <= h' < 5
    mask = (h_prime >= 4) & (h_prime < 5)
    r1[mask], g1[mask], b1[mask] = x[mask], 0, c[mask]
    # Sector 5: 5 <= h' < 6
    mask = (h_prime >= 5) & (h_prime < 6)
    r1[mask], g1[mask], b1[mask] = c[mask], 0, x[mask]

    rgb = np.stack([r1 + m, g1 + m, b1 + m], axis=-1)
    return np.clip(rgb * 255, 0, 255).astype(np.uint8)


def rgb_array_to_hsv(rgb):
    """
    Convert RGB array (H, W, 3) uint8 to HSV array (H, W, 3) float64.
    Output: H in [0, 360], S in [0, 1], V in [0, 1].
    """
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0

    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    # Value
    v = cmax

    # Saturation
    s = np.zeros_like(v)
    mask = cmax > 0
    s[mask] = delta[mask] / cmax[mask]

    # Hue
    h = np.zeros_like(v)
    mask_d = delta > 0
    mask_r = mask_d & (cmax == r)
    mask_g = mask_d & (cmax == g) & ~mask_r
    mask_b = mask_d & (cmax == b) & ~mask_r & ~mask_g

    h[mask_r] = 60.0 * (((g[mask_r] - b[mask_r]) / delta[mask_r]) % 6)
    h[mask_g] = 60.0 * ((b[mask_g] - r[mask_g]) / delta[mask_g] + 2)
    h[mask_b] = 60.0 * ((r[mask_b] - g[mask_b]) / delta[mask_b] + 4)

    return np.stack([h, s, v], axis=-1)


def hsv_array_to_rgb(hsv):
    """
    Convert HSV array (H, W, 3) float64 to RGB array (H, W, 3) uint8.
    Input: H in [0, 360], S in [0, 1], V in [0, 1].
    """
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    c = v * s
    h_prime = h / 60.0
    x = c * (1 - np.abs(h_prime % 2 - 1))
    m = v - c

    r1 = np.zeros_like(h)
    g1 = np.zeros_like(h)
    b1 = np.zeros_like(h)

    for i, (lo, hi) in enumerate([(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6)]):
        mask = (h_prime >= lo) & (h_prime < hi)
        if i == 0:
            r1[mask], g1[mask], b1[mask] = c[mask], x[mask], 0
        elif i == 1:
            r1[mask], g1[mask], b1[mask] = x[mask], c[mask], 0
        elif i == 2:
            r1[mask], g1[mask], b1[mask] = 0, c[mask], x[mask]
        elif i == 3:
            r1[mask], g1[mask], b1[mask] = 0, x[mask], c[mask]
        elif i == 4:
            r1[mask], g1[mask], b1[mask] = x[mask], 0, c[mask]
        elif i == 5:
            r1[mask], g1[mask], b1[mask] = c[mask], 0, x[mask]

    rgb = np.stack([r1 + m, g1 + m, b1 + m], axis=-1)
    return np.clip(rgb * 255, 0, 255).astype(np.uint8)


def rgb_array_to_hsi(rgb):
    """
    Convert RGB array (H, W, 3) uint8 to HSI array (H, W, 3) float64.
    Output: H in [0, 360], S in [0, 1], I in [0, 1].
    """
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0

    i = (r + g + b) / 3.0

    # Saturation
    min_rgb = np.minimum(np.minimum(r, g), b)
    s = np.zeros_like(i)
    mask = i > 0
    s[mask] = 1 - min_rgb[mask] / i[mask]

    # Hue
    num = 0.5 * ((r - g) + (r - b))
    den = np.sqrt((r - g) ** 2 + (r - b) * (g - b))
    den = np.maximum(den, 1e-10)  # Avoid division by zero

    theta = np.arccos(np.clip(num / den, -1, 1))
    h = np.where(b <= g, theta, 2 * np.pi - theta)
    h = np.degrees(h)

    return np.stack([h, s, i], axis=-1)


def hsi_array_to_rgb(hsi):
    """
    Convert HSI array (H, W, 3) float64 to RGB array (H, W, 3) uint8.
    Input: H in [0, 360], S in [0, 1], I in [0, 1].
    """
    h, s, i = hsi[..., 0], hsi[..., 1], hsi[..., 2]
    h_rad = np.radians(h % 360)

    r = np.zeros_like(h)
    g = np.zeros_like(h)
    b = np.zeros_like(h)

    # Sector 1: 0 <= H < 120
    mask = (h >= 0) & (h < 120)
    h1 = h_rad[mask]
    b[mask] = i[mask] * (1 - s[mask])
    cos_ratio = np.cos(h1) / np.maximum(np.cos(np.radians(60) - h1), 1e-10)
    r[mask] = i[mask] * (1 + s[mask] * cos_ratio)
    g[mask] = 3 * i[mask] - (r[mask] + b[mask])

    # Sector 2: 120 <= H < 240
    mask = (h >= 120) & (h < 240)
    h2 = np.radians(h[mask] - 120)
    r[mask] = i[mask] * (1 - s[mask])
    cos_ratio = np.cos(h2) / np.maximum(np.cos(np.radians(60) - h2), 1e-10)
    g[mask] = i[mask] * (1 + s[mask] * cos_ratio)
    b[mask] = 3 * i[mask] - (r[mask] + g[mask])

    # Sector 3: 240 <= H < 360
    mask = (h >= 240) & (h < 360)
    h3 = np.radians(h[mask] - 240)
    g[mask] = i[mask] * (1 - s[mask])
    cos_ratio = np.cos(h3) / np.maximum(np.cos(np.radians(60) - h3), 1e-10)
    b[mask] = i[mask] * (1 + s[mask] * cos_ratio)
    r[mask] = 3 * i[mask] - (g[mask] + b[mask])

    rgb = np.stack([r, g, b], axis=-1)
    return np.clip(rgb * 255, 0, 255).astype(np.uint8)


# ─── Flood Fill (still sequential, but optimized with numpy array access) ───

def create_magic_wand_mask(rgb_array, seed_point, threshold, cancel_event=None):
    """
    Flood-fill mask from seed_point within color distance threshold.
    Args:
        rgb_array: numpy array (H, W, 3) uint8
        seed_point: (x, y) tuple
        threshold: color distance threshold
        cancel_event: threading.Event for cancellation
    Returns:
        Boolean numpy array (H, W) where True = selected, or None if cancelled.
    """
    height, width = rgb_array.shape[:2]
    sx, sy = seed_point

    if sx < 0 or sx >= width or sy < 0 or sy >= height:
        return np.zeros((height, width), dtype=bool)

    seed_color = rgb_array[sy, sx].astype(np.float64)
    mask = np.zeros((height, width), dtype=bool)
    visited = np.zeros((height, width), dtype=bool)

    queue = [(sx, sy)]
    visited[sy, sx] = True
    check_interval = 1000  # Check cancel every N pixels

    count = 0
    while queue:
        count += 1
        if count % check_interval == 0 and cancel_event and cancel_event.is_set():
            return None

        x, y = queue.pop()
        px = rgb_array[y, x].astype(np.float64)
        dist = np.sqrt(np.sum((seed_color - px) ** 2))

        if dist <= threshold:
            mask[y, x] = True
            for nx, ny in [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]:
                if 0 <= nx < width and 0 <= ny < height and not visited[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((nx, ny))

    return mask


def dilate_mask(mask, amount):
    """Dilate a boolean mask by amount pixels using numpy array shifts."""
    if amount <= 0:
        return mask
    result = mask.copy()
    for _ in range(amount):
        # Expand in all 4 directions
        padded = np.pad(result, 1, mode='constant', constant_values=False)
        result = (
            padded[1:-1, 1:-1] |  # center
            padded[:-2, 1:-1] |   # up
            padded[2:, 1:-1] |    # down
            padded[1:-1, :-2] |   # left
            padded[1:-1, 2:]      # right
        )
    return result


# ─── Main Processing Function ───────────────────────────────────────────────

def process_background_removal(image, points, alpha_threshold, color_space,
                               cancel_event=None):
    """
    Process background removal using vectorized numpy operations.
    - points: list of dicts {x, y, threshold, feathering}
    - alpha_threshold: threshold for deciding full-transparent vs partial transparency
    - color_space: 'HSL', 'HSV', or 'HSI'
    - cancel_event: threading.Event, if set the processing aborts and returns None
    Returns RGBA Image with background removed, or None if cancelled.
    """
    if not points:
        return image.convert("RGBA")

    rgb_image = image.convert("RGB")
    rgb_array = np.array(rgb_image)  # (H, W, 3) uint8
    height, width = rgb_array.shape[:2]

    # Build combined mask from all points
    combined_mask = np.zeros((height, width), dtype=bool)

    for pt in points:
        if cancel_event and cancel_event.is_set():
            return None

        pt_mask = create_magic_wand_mask(
            rgb_array, (pt["x"], pt["y"]), pt["threshold"], cancel_event
        )
        if pt_mask is None:
            return None

        pt_mask = dilate_mask(pt_mask, pt["feathering"])
        combined_mask |= pt_mask

    if cancel_event and cancel_event.is_set():
        return None

    # ─── Vectorized pixel processing ────────────────────────────────────

    # Compute minimum color distance to any seed point for all masked pixels
    # Collect seed colors
    seed_colors = []
    for pt in points:
        px, py = pt["x"], pt["y"]
        if 0 <= px < width and 0 <= py < height:
            seed_colors.append(rgb_array[py, px].astype(np.float64))

    if not seed_colors:
        return image.convert("RGBA")

    seed_colors = np.array(seed_colors)  # (N, 3)

    # Get masked pixel coordinates
    masked_pixels = rgb_array[combined_mask].astype(np.float64)  # (M, 3)

    if cancel_event and cancel_event.is_set():
        return None

    # Compute distance from each masked pixel to each seed color
    # masked_pixels: (M, 3), seed_colors: (N, 3)
    # Result: (M,) minimum distance
    # Process in chunks to avoid huge memory allocation
    chunk_size = 100000
    num_masked = masked_pixels.shape[0]
    min_distances = np.empty(num_masked, dtype=np.float64)

    for start in range(0, num_masked, chunk_size):
        if cancel_event and cancel_event.is_set():
            return None
        end = min(start + chunk_size, num_masked)
        chunk = masked_pixels[start:end]  # (chunk, 3)
        # Broadcast: (chunk, 1, 3) - (1, N, 3) -> (chunk, N, 3)
        diffs = chunk[:, np.newaxis, :] - seed_colors[np.newaxis, :, :]
        dists = np.sqrt(np.sum(diffs ** 2, axis=2))  # (chunk, N)
        min_distances[start:end] = np.min(dists, axis=1)

    if cancel_event and cancel_event.is_set():
        return None

    # Classify pixels: fully transparent vs partial
    fully_transparent = min_distances <= alpha_threshold
    partial_mask = ~fully_transparent

    # Build result RGBA array
    result = np.zeros((height, width, 4), dtype=np.uint8)
    result[..., :3] = rgb_array
    result[..., 3] = 255  # Default fully opaque

    # Fully transparent pixels
    mask_indices = np.where(combined_mask)
    full_trans_indices = (mask_indices[0][fully_transparent], mask_indices[1][fully_transparent])
    result[full_trans_indices[0], full_trans_indices[1]] = [0, 0, 0, 0]

    # Partial transparency pixels — need color space conversion
    if np.any(partial_mask):
        partial_indices = (mask_indices[0][partial_mask], mask_indices[1][partial_mask])
        partial_rgb = rgb_array[partial_indices[0], partial_indices[1]]  # (P, 3)

        # Choose color space
        if color_space == "HSL":
            to_cs = rgb_array_to_hsl
            from_cs = hsl_array_to_rgb
        elif color_space == "HSV":
            to_cs = rgb_array_to_hsv
            from_cs = hsv_array_to_rgb
        else:  # HSI
            to_cs = rgb_array_to_hsi
            from_cs = hsi_array_to_rgb

        # Reshape to (P, 1, 3) for the conversion functions that expect (H, W, 3)
        partial_rgb_3d = partial_rgb[:, np.newaxis, :]  # (P, 1, 3)
        cs_values = to_cs(partial_rgb_3d)  # (P, 1, 3)

        # Lightness/Value/Intensity is always index 2
        lightness = cs_values[:, 0, 2]  # (P,)

        # Alpha = inverted lightness
        alpha = ((1.0 - lightness) * 255).astype(np.uint8)

        # Set lightness to 0 and convert back
        cs_values[:, 0, 2] = 0
        new_rgb = from_cs(cs_values)[:, 0, :]  # (P, 3)

        # Write results
        result[partial_indices[0], partial_indices[1], :3] = new_rgb
        result[partial_indices[0], partial_indices[1], 3] = alpha

    return Image.fromarray(result, "RGBA")
