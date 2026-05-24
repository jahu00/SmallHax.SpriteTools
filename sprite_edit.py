"""Sprite edit processing functions.

Splits an image into tiles based on tile size and grid dimensions,
applies per-tile horizontal/vertical flips, and reassembles the tiles
into an output image with a potentially different number of rows/columns.
"""

from PIL import Image


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
