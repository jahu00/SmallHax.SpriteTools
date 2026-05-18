"""Image scaling processing functions with optional preprocessing filters."""

import numpy as np
from PIL import Image, ImageFilter


# ─── Preprocessing Filters ──────────────────────────────────────────────────


def _brightness(pixel):
    """Compute perceived brightness of an RGB pixel."""
    return 0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2]


def apply_erode(image, kernel_size=3, kernel_shape="square"):
    """Erode based on pixel brightness while retaining color.

    Replaces each pixel with the darkest pixel in the kernel neighborhood.

    Args:
        image: PIL Image (RGB or RGBA).
        kernel_size: Size of the kernel (will be forced to 2*n+1 form).
        kernel_shape: 'square' or 'round'.

    Returns:
        Processed PIL Image.
    """
    has_alpha = image.mode == "RGBA"
    if has_alpha:
        rgb = image.convert("RGB")
        alpha = image.split()[3]
    else:
        rgb = image.convert("RGB")
        alpha = None

    arr = np.array(rgb, dtype=np.float64)
    h, w, _ = arr.shape

    # Ensure odd kernel size
    n = max(0, (kernel_size - 1) // 2)
    radius = n

    # Build kernel mask
    mask = _build_kernel_mask(radius, kernel_shape)

    # Compute brightness
    brightness = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]

    # Pad arrays
    padded_brightness = np.pad(brightness, radius, mode="edge")
    padded_arr = np.pad(arr, ((radius, radius), (radius, radius), (0, 0)), mode="edge")

    result = np.empty_like(arr)

    # For each pixel, find the darkest neighbor within the kernel
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if not mask[dy + radius, dx + radius]:
                continue
            # On first valid offset, initialize
            shifted_b = padded_brightness[radius + dy:radius + dy + h,
                                          radius + dx:radius + dx + w]
            shifted_c = padded_arr[radius + dy:radius + dy + h,
                                   radius + dx:radius + dx + w]
            if dy == -radius and dx == -radius:
                min_brightness = shifted_b.copy()
                result[:] = shifted_c
            else:
                update_mask = shifted_b < min_brightness
                min_brightness = np.where(update_mask, shifted_b, min_brightness)
                for c in range(3):
                    result[:, :, c] = np.where(update_mask, shifted_c[:, :, c], result[:, :, c])

    out = Image.fromarray(result.clip(0, 255).astype(np.uint8), "RGB")
    if has_alpha:
        out.putalpha(alpha)
    return out


def apply_dilate(image, kernel_size=3, kernel_shape="square"):
    """Dilate based on pixel brightness while retaining color.

    Replaces each pixel with the brightest pixel in the kernel neighborhood.

    Args:
        image: PIL Image (RGB or RGBA).
        kernel_size: Size of the kernel (will be forced to 2*n+1 form).
        kernel_shape: 'square' or 'round'.

    Returns:
        Processed PIL Image.
    """
    has_alpha = image.mode == "RGBA"
    if has_alpha:
        rgb = image.convert("RGB")
        alpha = image.split()[3]
    else:
        rgb = image.convert("RGB")
        alpha = None

    arr = np.array(rgb, dtype=np.float64)
    h, w, _ = arr.shape

    n = max(0, (kernel_size - 1) // 2)
    radius = n

    mask = _build_kernel_mask(radius, kernel_shape)

    brightness = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]

    padded_brightness = np.pad(brightness, radius, mode="edge")
    padded_arr = np.pad(arr, ((radius, radius), (radius, radius), (0, 0)), mode="edge")

    result = np.empty_like(arr)

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if not mask[dy + radius, dx + radius]:
                continue
            shifted_b = padded_brightness[radius + dy:radius + dy + h,
                                          radius + dx:radius + dx + w]
            shifted_c = padded_arr[radius + dy:radius + dy + h,
                                   radius + dx:radius + dx + w]
            if dy == -radius and dx == -radius:
                max_brightness = shifted_b.copy()
                result[:] = shifted_c
            else:
                update_mask = shifted_b > max_brightness
                max_brightness = np.where(update_mask, shifted_b, max_brightness)
                for c in range(3):
                    result[:, :, c] = np.where(update_mask, shifted_c[:, :, c], result[:, :, c])

    out = Image.fromarray(result.clip(0, 255).astype(np.uint8), "RGB")
    if has_alpha:
        out.putalpha(alpha)
    return out


def apply_frequency_filter(image, kernel_size=3, kernel_shape="square"):
    """Replace each pixel with the most popular color in the kernel window.

    Uses a mode-like approach: for each pixel, find the color that appears
    most frequently in the neighborhood.

    Args:
        image: PIL Image (RGB or RGBA).
        kernel_size: Size of the kernel (2*n+1 formula).
        kernel_shape: 'square' or 'round'.

    Returns:
        Processed PIL Image.
    """
    has_alpha = image.mode == "RGBA"
    if has_alpha:
        rgb = image.convert("RGB")
        alpha = image.split()[3]
    else:
        rgb = image.convert("RGB")
        alpha = None

    arr = np.array(rgb, dtype=np.uint8)
    h, w, _ = arr.shape

    n = max(0, (kernel_size - 1) // 2)
    radius = n

    mask = _build_kernel_mask(radius, kernel_shape)

    # Quantize colors to reduce unique count (shift right by 2 bits)
    quantized = (arr >> 2).astype(np.uint32)
    # Encode as single int: R*64*64 + G*64 + B
    encoded = quantized[:, :, 0] * 4096 + quantized[:, :, 1] * 64 + quantized[:, :, 2]

    padded_encoded = np.pad(encoded, radius, mode="edge")
    padded_arr = np.pad(arr, ((radius, radius), (radius, radius), (0, 0)), mode="edge")

    result = np.empty_like(arr)

    # Collect kernel offsets
    offsets = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if mask[dy + radius, dx + radius]:
                offsets.append((dy, dx))

    # Process in blocks for memory efficiency
    block_size = 64
    for by in range(0, h, block_size):
        by_end = min(by + block_size, h)
        bh = by_end - by
        for bx in range(0, w, block_size):
            bx_end = min(bx + block_size, w)
            bw = bx_end - bx

            # Gather all neighbor encoded values for this block
            neighbors_enc = np.empty((bh, bw, len(offsets)), dtype=np.uint32)
            neighbors_r = np.empty((bh, bw, len(offsets)), dtype=np.uint8)
            neighbors_g = np.empty((bh, bw, len(offsets)), dtype=np.uint8)
            neighbors_b = np.empty((bh, bw, len(offsets)), dtype=np.uint8)

            for oi, (dy, dx) in enumerate(offsets):
                sy = radius + by + dy
                sx = radius + bx + dx
                neighbors_enc[:, :, oi] = padded_encoded[sy:sy + bh, sx:sx + bw]
                neighbors_r[:, :, oi] = padded_arr[sy:sy + bh, sx:sx + bw, 0]
                neighbors_g[:, :, oi] = padded_arr[sy:sy + bh, sx:sx + bw, 1]
                neighbors_b[:, :, oi] = padded_arr[sy:sy + bh, sx:sx + bw, 2]

            # For each pixel in the block, find the most common encoded value
            for py in range(bh):
                for px in range(bw):
                    enc_vals = neighbors_enc[py, px]
                    # Find mode
                    unique, counts = np.unique(enc_vals, return_counts=True)
                    mode_idx = np.argmax(counts)
                    mode_val = unique[mode_idx]
                    # Find first occurrence of mode in neighbors
                    match_idx = np.where(enc_vals == mode_val)[0][0]
                    result[by + py, bx + px, 0] = neighbors_r[py, px, match_idx]
                    result[by + py, bx + px, 1] = neighbors_g[py, px, match_idx]
                    result[by + py, bx + px, 2] = neighbors_b[py, px, match_idx]

    out = Image.fromarray(result, "RGB")
    if has_alpha:
        out.putalpha(alpha)
    return out


def apply_blur(image, kernel_size=3, kernel_shape="square"):
    """Apply a blur filter using the given kernel size and shape.

    Args:
        image: PIL Image (RGB or RGBA).
        kernel_size: Size of the kernel (2*n+1 formula).
        kernel_shape: 'square' or 'round'.

    Returns:
        Processed PIL Image.
    """
    has_alpha = image.mode == "RGBA"
    if has_alpha:
        rgb = image.convert("RGB")
        alpha = image.split()[3]
    else:
        rgb = image.convert("RGB")
        alpha = None

    arr = np.array(rgb, dtype=np.float64)
    h, w, _ = arr.shape

    n = max(0, (kernel_size - 1) // 2)
    radius = n

    mask = _build_kernel_mask(radius, kernel_shape)
    kernel_count = mask.sum()

    if kernel_count == 0:
        return image

    padded = np.pad(arr, ((radius, radius), (radius, radius), (0, 0)), mode="edge")

    # Sum over kernel
    accum = np.zeros_like(arr)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if mask[dy + radius, dx + radius]:
                accum += padded[radius + dy:radius + dy + h,
                                radius + dx:radius + dx + w]

    result = (accum / kernel_count).clip(0, 255).astype(np.uint8)

    out = Image.fromarray(result, "RGB")
    if has_alpha:
        out.putalpha(alpha)
    return out


def _build_kernel_mask(radius, kernel_shape):
    """Build a boolean kernel mask.

    Args:
        radius: Half-size of the kernel (full size is 2*radius+1).
        kernel_shape: 'square' or 'round'.

    Returns:
        2D numpy boolean array of shape (2*radius+1, 2*radius+1).
    """
    size = 2 * radius + 1
    if kernel_shape == "round":
        yy, xx = np.ogrid[:size, :size]
        center = radius
        dist_sq = (xx - center) ** 2 + (yy - center) ** 2
        return dist_sq <= radius * radius
    else:
        return np.ones((size, size), dtype=bool)


# ─── Scaling Functions ───────────────────────────────────────────────────────

# Available resampling methods
RESAMPLE_METHODS = {
    "Nearest": Image.NEAREST,
    "Bilinear": Image.BILINEAR,
    "Bicubic": Image.BICUBIC,
    "Lanczos": Image.LANCZOS,
    "Box": Image.BOX,
    "Hamming": Image.HAMMING,
}


def scale_image(image, target_width, target_height, resample_method="Lanczos",
                filters=None, cancel_event=None):
    """Scale an image to the target dimensions with optional preprocessing.

    Args:
        image: Source PIL Image.
        target_width: Target width in pixels.
        target_height: Target height in pixels.
        resample_method: Name of the resampling method (key from RESAMPLE_METHODS).
        filters: Optional list of filter dicts to apply before scaling.
            Each dict has: {'type': str, 'kernel_size': int, 'kernel_shape': str}
            Types: 'erode', 'dilate', 'frequency', 'blur'
        cancel_event: Optional threading.Event to check for cancellation.

    Returns:
        Scaled PIL Image, or None if cancelled.
    """
    if target_width <= 0 or target_height <= 0:
        return None

    result = image.copy()

    # Apply preprocessing filters in order
    if filters:
        for f in filters:
            if cancel_event and cancel_event.is_set():
                return None

            ftype = f.get("type", "")
            kernel_size = f.get("kernel_size", 3)
            kernel_shape = f.get("kernel_shape", "square")

            if ftype == "erode":
                result = apply_erode(result, kernel_size, kernel_shape)
            elif ftype == "dilate":
                result = apply_dilate(result, kernel_size, kernel_shape)
            elif ftype == "frequency":
                result = apply_frequency_filter(result, kernel_size, kernel_shape)
            elif ftype == "blur":
                result = apply_blur(result, kernel_size, kernel_shape)

    if cancel_event and cancel_event.is_set():
        return None

    # Scale
    resample = RESAMPLE_METHODS.get(resample_method, Image.LANCZOS)
    result = result.resize((int(target_width), int(target_height)), resample)

    return result


def scale_tileset(image, tile_cols, tile_rows, target_tile_width, target_tile_height,
                  resample_method="Lanczos", filters=None, cancel_event=None):
    """Scale a tileset so each tile becomes the target tile size.

    The image is treated as a grid of tile_cols x tile_rows tiles.
    Each tile is individually scaled to target_tile_width x target_tile_height,
    then reassembled.

    Args:
        image: Source PIL Image (the sprite sheet).
        tile_cols: Number of tile columns in the sheet.
        tile_rows: Number of tile rows in the sheet.
        target_tile_width: Desired width of each tile in pixels.
        target_tile_height: Desired height of each tile in pixels.
        resample_method: Resampling method name.
        filters: Optional preprocessing filters (applied per-tile).
        cancel_event: Optional threading.Event for cancellation.

    Returns:
        Scaled PIL Image, or None if cancelled.
    """
    if tile_cols <= 0 or tile_rows <= 0:
        return None
    if target_tile_width <= 0 or target_tile_height <= 0:
        return None

    img_w, img_h = image.size
    src_tile_w = img_w / tile_cols
    src_tile_h = img_h / tile_rows

    out_w = target_tile_width * tile_cols
    out_h = target_tile_height * tile_rows
    result = Image.new(image.mode, (out_w, out_h))

    for row in range(tile_rows):
        for col in range(tile_cols):
            if cancel_event and cancel_event.is_set():
                return None

            # Crop tile
            x0 = int(col * src_tile_w)
            y0 = int(row * src_tile_h)
            x1 = int((col + 1) * src_tile_w)
            y1 = int((row + 1) * src_tile_h)
            tile = image.crop((x0, y0, x1, y1))

            # Scale tile
            scaled_tile = scale_image(
                tile, target_tile_width, target_tile_height,
                resample_method, filters, cancel_event
            )
            if scaled_tile is None:
                return None

            # Paste into result
            result.paste(scaled_tile, (col * target_tile_width, row * target_tile_height))

    return result
