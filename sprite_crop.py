"""Sprite crop processing functions."""

from PIL import Image


def compute_tile_rects(img_width, img_height, margin_top, margin_bottom,
                       margin_left, margin_right, rows, cols,
                       inner_h, inner_v):
    """Compute tile rectangles for a sprite sheet grid.

    The inner margin is applied uniformly to both sides of each tile.
    For example, with inner_h=4, each tile is inset by 4px on its left
    and 4px on its right, producing 8px of space between adjacent tiles.

    Args:
        img_width: Source image width in pixels.
        img_height: Source image height in pixels.
        margin_top: Outer margin from top edge.
        margin_bottom: Outer margin from bottom edge.
        margin_left: Outer margin from left edge.
        margin_right: Outer margin from right edge.
        rows: Number of tile rows.
        cols: Number of tile columns.
        inner_h: Horizontal margin applied to each side of a tile.
        inner_v: Vertical margin applied to each side of a tile.

    Returns:
        A list of (x, y, w, h) tuples in image coordinates,
        or None if parameters produce invalid geometry.
    """
    content_x = margin_left
    content_y = margin_top
    content_w = img_width - margin_left - margin_right
    content_h = img_height - margin_top - margin_bottom

    if content_w <= 0 or content_h <= 0:
        return None

    # Each tile occupies a cell. Between adjacent tiles the spacing is
    # inner_h * 2 (one margin from each side). The outer tiles also have
    # the margin on their outer edge within the content area.
    # Total horizontal space consumed by margins: inner_h * 2 * cols
    total_margin_h = inner_h * 2 * cols
    total_margin_v = inner_v * 2 * rows

    tile_w = (content_w - total_margin_h) / cols
    tile_h = (content_h - total_margin_v) / rows

    if tile_w <= 0 or tile_h <= 0:
        return None

    # Cell size (tile + margins on both sides)
    cell_w = tile_w + inner_h * 2
    cell_h = tile_h + inner_v * 2

    rects = []
    for row in range(rows):
        for col in range(cols):
            x = content_x + col * cell_w + inner_h
            y = content_y + row * cell_h + inner_v
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


def crop_all_tiles(image, rects, rows, cols):
    """Crop all tiles and reconstruct them into a single image.

    Tiles are placed in a grid with no margins — each tile directly
    adjacent to its neighbours.

    Args:
        image: Source PIL Image.
        rects: List of (x, y, w, h) tuples from compute_tile_rects.
        rows: Number of tile rows.
        cols: Number of tile columns.

    Returns:
        A single PIL Image containing all tiles arranged in the grid,
        or None if rects is empty.
    """
    if not rects:
        return None

    # All tiles share the same dimensions
    _, _, tile_w, tile_h = rects[0]
    tw = int(tile_w)
    th = int(tile_h)

    if tw <= 0 or th <= 0:
        return None

    out_w = tw * cols
    out_h = th * rows

    result = Image.new(image.mode, (out_w, out_h))

    for idx, (x, y, w, h) in enumerate(rects):
        tile = image.crop((int(x), int(y), int(x + w), int(y + h)))
        row = idx // cols
        col = idx % cols
        result.paste(tile, (col * tw, row * th))

    return result
