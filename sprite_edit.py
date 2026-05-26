"""Sprite edit processing functions.

Splits an image into tiles based on tile size and grid dimensions,
applies per-tile horizontal/vertical flips, and reassembles the tiles
into an output image with a potentially different number of rows/columns.
"""

from typing import Optional

from PIL import Image

from scaling import RESAMPLE_METHODS


def apply_margin_crop(image: Image.Image, top: int, bottom: int, left: int, right: int) -> Optional[Image.Image]:
    """Apply margin/crop to an image.

    Positive values trim pixels from that edge.
    Negative values add transparent padding to that edge.
    Returns None if the result would have zero or negative dimensions.
    """
    w, h = image.size

    # Clamp opposing positive margins so at least 1 pixel remains per axis
    # Only clamp positive values (trimming); negative values (padding) don't reduce dimensions
    eff_top = top
    eff_bottom = bottom
    eff_left = left
    eff_right = right

    # For vertical axis: clamp if sum of positive trims >= image height
    pos_top = max(eff_top, 0)
    pos_bottom = max(eff_bottom, 0)
    if pos_top + pos_bottom >= h:
        # Scale both down proportionally so that at least 1 pixel remains
        total = pos_top + pos_bottom
        # Clamp: reduce each proportionally so their sum = h - 1
        if total > 0:
            eff_top = int(pos_top * (h - 1) / total)
            eff_bottom = (h - 1) - eff_top

    # For horizontal axis: clamp if sum of positive trims >= image width
    pos_left = max(eff_left, 0)
    pos_right = max(eff_right, 0)
    if pos_left + pos_right >= w:
        total = pos_left + pos_right
        if total > 0:
            eff_left = int(pos_left * (w - 1) / total)
            eff_right = (w - 1) - eff_left

    # Compute resulting dimensions
    # Positive margins reduce size, negative margins increase size
    new_w = w - eff_left - eff_right  # negative eff values add width
    new_h = h - eff_top - eff_bottom  # negative eff values add height

    if new_w <= 0 or new_h <= 0:
        return None

    # Ensure source image is RGBA for transparent padding
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    # Determine crop box from original image (only positive trims)
    crop_left = max(eff_left, 0)
    crop_top = max(eff_top, 0)
    crop_right = w - max(eff_right, 0)
    crop_bottom = h - max(eff_bottom, 0)

    cropped = image.crop((crop_left, crop_top, crop_right, crop_bottom))

    # Determine padding (only negative margins add padding)
    pad_left = abs(min(eff_left, 0))
    pad_top = abs(min(eff_top, 0))
    pad_right = abs(min(eff_right, 0))
    pad_bottom = abs(min(eff_bottom, 0))

    if pad_left == 0 and pad_top == 0 and pad_right == 0 and pad_bottom == 0:
        # No padding needed, just return the cropped image
        return cropped

    # Create new image with padding (transparent)
    result = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    result.paste(cropped, (pad_left, pad_top))

    return result


def apply_offset(image: Image.Image, offset_x: int, offset_y: int) -> Image.Image:
    """Shift image content by (offset_x, offset_y) pixels.

    Vacated areas are filled with transparent pixels.
    Positive X shifts right, positive Y shifts down.
    """
    w, h = image.size

    # Ensure source image is RGBA for transparent handling
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    # Create a new transparent image of the same dimensions
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # Paste the original image at the offset position
    result.paste(image, (offset_x, offset_y))

    return result


def apply_tweak_scale(image: Image.Image, scale_percent: int, resample_method: str) -> Image.Image:
    """Scale image uniformly by the given percentage.

    scale_percent: 1-1000 (100 = no change).
    Uses the specified resampling method.
    """
    w, h = image.size
    new_w = max(1, round(w * scale_percent / 100))
    new_h = max(1, round(h * scale_percent / 100))
    resample = RESAMPLE_METHODS.get(resample_method, Image.LANCZOS)
    return image.resize((new_w, new_h), resample)


def scale_to_tile_size(image: Image.Image, tile_w: int, tile_h: int, resample_method: str) -> Image.Image:
    """Scale image to exactly tile_w × tile_h using the specified method.

    Args:
        image: Source PIL Image to scale.
        tile_w: Target width in pixels.
        tile_h: Target height in pixels.
        resample_method: Name of the resampling method (e.g., "Lanczos", "Nearest").
            If unknown, defaults to LANCZOS.

    Returns:
        A new PIL Image scaled to exactly (tile_w, tile_h).
    """
    resample = RESAMPLE_METHODS.get(resample_method, Image.LANCZOS)
    return image.resize((tile_w, tile_h), resample)


def process_imported_tile(image: Image.Image, margin_top: int, margin_bottom: int,
                          margin_left: int, margin_right: int,
                          offset_x: int, offset_y: int,
                          tweak_scale: int, tile_w: int, tile_h: int,
                          resample_method: str) -> Optional[Image.Image]:
    """Run the full import processing pipeline.

    Pipeline order: margin/crop → offset → tweak scale → final scale to tile size.
    Returns None if margin/crop reduces dimensions to zero.
    """
    # Step 1: Margin/crop
    result = apply_margin_crop(image, margin_top, margin_bottom, margin_left, margin_right)
    if result is None:
        return None

    # Step 2: Offset
    result = apply_offset(result, offset_x, offset_y)

    # Step 3: Tweak scale
    result = apply_tweak_scale(result, tweak_scale, resample_method)

    # Step 4: Final scale to tile size
    result = scale_to_tile_size(result, tile_w, tile_h, resample_method)

    return result


def compute_tile_rects(img_width, img_height, tile_w, tile_h, rows, cols):
    """Compute tile rectangles for a sprite sheet grid (no margins).

    Args:
        img_width: Source image width in pixels.
        img_height: Source image height in pixels.
        tile_w: Width of each tile in pixels.
        tile_h: Height of each tile in pixels.
        rows: Number of tile rows.
        cols: Number of tile columns.

    Returns:
        A list of (x, y, w, h) tuples in image coordinates,
        or None if parameters produce invalid geometry.
    """
    if tile_w <= 0 or tile_h <= 0:
        return None
    if rows <= 0 or cols <= 0:
        return None

    needed_w = tile_w * cols
    needed_h = tile_h * rows

    if needed_w > img_width or needed_h > img_height:
        return None

    rects = []
    for row in range(rows):
        for col in range(cols):
            x = col * tile_w
            y = row * tile_h
            rects.append((x, y, tile_w, tile_h))

    return rects


def crop_tile(image, rects, index):
    """Crop a single tile from the source image.

    Args:
        image: Source PIL Image.
        rects: List of (x, y, w, h) tuples from compute_tile_rects.
        index: Index of the tile to crop.

    Returns:
        A cropped PIL Image, or None if index is out of range.
    """
    if not rects or index < 0 or index >= len(rects):
        return None

    x, y, tw, th = rects[index]
    return image.crop((int(x), int(y), int(x + tw), int(y + th)))


def apply_tile_flips(image, rects, flip_h_set, flip_v_set):
    """Apply per-tile flips and return a list of tile images.

    Args:
        image: Source PIL Image.
        rects: List of (x, y, w, h) tuples.
        flip_h_set: Set of tile indices to flip horizontally.
        flip_v_set: Set of tile indices to flip vertically.

    Returns:
        A list of PIL Images (one per tile), with flips applied.
    """
    tiles = []
    for idx, (x, y, tw, th) in enumerate(rects):
        tile = image.crop((int(x), int(y), int(x + tw), int(y + th)))
        if idx in flip_h_set:
            tile = tile.transpose(Image.FLIP_LEFT_RIGHT)
        if idx in flip_v_set:
            tile = tile.transpose(Image.FLIP_TOP_BOTTOM)
        tiles.append(tile)
    return tiles


def reassemble_tiles(tiles, tile_w, tile_h, out_cols, out_rows, image_mode="RGBA"):
    """Reassemble tile images into a single output image.

    Tiles are placed row by row. If there are fewer tiles than
    out_cols * out_rows, remaining cells are left transparent/black.

    Args:
        tiles: List of PIL Images (already flipped as needed).
        tile_w: Width of each tile.
        tile_h: Height of each tile.
        out_cols: Number of columns in the output image.
        out_rows: Number of rows in the output image.
        image_mode: Mode for the output image.

    Returns:
        A single PIL Image, or None if parameters are invalid.
    """
    if tile_w <= 0 or tile_h <= 0 or out_cols <= 0 or out_rows <= 0:
        return None

    out_w = int(tile_w * out_cols)
    out_h = int(tile_h * out_rows)

    result = Image.new(image_mode, (out_w, out_h))

    for idx, tile in enumerate(tiles):
        if idx >= out_cols * out_rows:
            break
        row = idx // out_cols
        col = idx % out_cols
        result.paste(tile, (col * int(tile_w), row * int(tile_h)))

    return result
