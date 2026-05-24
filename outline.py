"""Outline tool processing functions.

Creates an outline around the foreground of an image by:
1. Building a background mask from user-selected sample points (flood fill)
2. Inverting to get the foreground mask
3. Optionally smoothing the foreground mask (Gaussian blur + threshold)
4. Dilating the foreground mask by a thickness value
5. Subtracting the original foreground mask from the dilated mask to get the outline ring
6. Filling the outline ring with a user-chosen color
7. Compositing the outline behind or above the input image
"""

import numpy as np
from PIL import Image, ImageFilter

from bg_removal import create_magic_wand_mask, feather_mask, dilate_mask


def smooth_mask(mask, radius):
    """Smooth a boolean mask using Gaussian blur and re-threshold.

    Converts the mask to a grayscale image, applies a Gaussian blur,
    then thresholds at 50% to get a smoothed boolean mask.

    Args:
        mask: Boolean numpy array (H, W).
        radius: Blur radius (strength). Higher = smoother.

    Returns:
        Smoothed boolean numpy array (H, W).
    """
    if radius <= 0:
        return mask

    # Convert bool mask to 0/255 grayscale PIL Image
    mask_img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")

    # Apply Gaussian blur
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=radius))

    # Threshold back to boolean at 50%
    smoothed = np.array(mask_img) >= 128

    return smoothed


def compute_outline(image, points, thickness, outline_color, mode="behind",
                    smooth=False, smooth_radius=2, cancel_event=None):
    """Compute an outline around the foreground of the image.

    Args:
        image: Source PIL Image (any mode, will be converted to RGBA).
        points: List of dicts {x, y, threshold, feathering} for background samples.
        thickness: Number of pixels to dilate for the outline.
        outline_color: (R, G, B) tuple for the outline color.
        mode: "behind" to place outline behind the image, "above" to place on top.
        smooth: Whether to smooth the foreground mask before outlining.
        smooth_radius: Gaussian blur radius for smoothing.
        cancel_event: threading.Event for cancellation.

    Returns:
        RGBA PIL Image with outline applied, or None if cancelled or invalid.
    """
    if not points or thickness <= 0:
        return image.convert("RGBA")

    rgba_image = image.convert("RGBA")
    rgb_array = np.array(rgba_image.convert("RGB"))  # (H, W, 3) uint8
    height, width = rgb_array.shape[:2]

    # Build combined background mask from all sample points
    bg_mask = np.zeros((height, width), dtype=bool)

    for pt in points:
        if cancel_event and cancel_event.is_set():
            return None

        pt_mask = create_magic_wand_mask(
            rgb_array, (pt["x"], pt["y"]), pt["threshold"], cancel_event
        )
        if pt_mask is None:
            return None

        # Only apply positive feathering (dilate bg mask) here
        feathering = pt.get("feathering", 0)
        if feathering > 0:
            pt_mask = feather_mask(pt_mask, feathering)
        bg_mask |= pt_mask

    if cancel_event and cancel_event.is_set():
        return None

    # Foreground mask = inverse of background
    fg_mask = ~bg_mask

    # Negative feathering: expand the foreground mask by dilating it
    # (uses the feathering value from the first point as the global value)
    if points:
        feathering = points[0].get("feathering", 0)
        if feathering < 0:
            fg_mask = dilate_mask(fg_mask, abs(feathering))

    # Optional smoothing of the foreground mask
    if smooth and smooth_radius > 0:
        fg_mask = smooth_mask(fg_mask, smooth_radius)

    # Dilate the foreground mask by thickness
    dilated_fg = dilate_mask(fg_mask, thickness)

    if cancel_event and cancel_event.is_set():
        return None

    # Outline ring = dilated foreground minus original foreground
    outline_mask = dilated_fg & ~fg_mask

    if cancel_event and cancel_event.is_set():
        return None

    # Build the outline layer (RGBA)
    outline_layer = np.zeros((height, width, 4), dtype=np.uint8)
    outline_layer[outline_mask, 0] = outline_color[0]
    outline_layer[outline_mask, 1] = outline_color[1]
    outline_layer[outline_mask, 2] = outline_color[2]
    outline_layer[outline_mask, 3] = 255

    # Composite
    source_array = np.array(rgba_image)

    if mode == "behind":
        # Outline behind: start with outline, paste source on top
        result = outline_layer.copy()
        # Alpha compositing: source over outline
        src_alpha = source_array[..., 3:4].astype(np.float64) / 255.0
        dst_alpha = result[..., 3:4].astype(np.float64) / 255.0

        out_alpha = src_alpha + dst_alpha * (1 - src_alpha)
        out_alpha_safe = np.maximum(out_alpha, 1e-10)

        out_rgb = (
            source_array[..., :3].astype(np.float64) * src_alpha +
            result[..., :3].astype(np.float64) * dst_alpha * (1 - src_alpha)
        ) / out_alpha_safe

        result[..., :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
        result[..., 3] = np.clip(out_alpha[..., 0] * 255, 0, 255).astype(np.uint8)
    else:
        # Outline above: start with source, paste outline on top
        result = source_array.copy()
        # Alpha compositing: outline over source
        src_alpha = outline_layer[..., 3:4].astype(np.float64) / 255.0
        dst_alpha = result[..., 3:4].astype(np.float64) / 255.0

        out_alpha = src_alpha + dst_alpha * (1 - src_alpha)
        out_alpha_safe = np.maximum(out_alpha, 1e-10)

        out_rgb = (
            outline_layer[..., :3].astype(np.float64) * src_alpha +
            result[..., :3].astype(np.float64) * dst_alpha * (1 - src_alpha)
        ) / out_alpha_safe

        result[..., :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
        result[..., 3] = np.clip(out_alpha[..., 0] * 255, 0, 255).astype(np.uint8)

    return Image.fromarray(result, "RGBA")
