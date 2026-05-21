"""Geometry correction processing logic.

Computes affine scaling (ax + b) for both X and Y axes based on
user-provided point pairs (actual position vs. expected position),
then applies the transformation to the image.
"""

import numpy as np
from PIL import Image

from scaling import RESAMPLE_METHODS


def compute_geometry_coefficients(points):
    """Compute linear regression (ax + b) for X and Y axes.

    Each point has actual (img_x, img_y) and expected (exp_x, exp_y) coords.
    We fit: exp_x = a_x * img_x + b_x
            exp_y = a_y * img_y + b_y

    Args:
        points: List of dicts with keys: img_x, img_y, exp_x, exp_y.

    Returns:
        Dict with keys: a_x, b_x, a_y, b_y, or None if insufficient points.
    """
    if len(points) < 2:
        return None

    img_x = np.array([p["img_x"] for p in points], dtype=np.float64)
    img_y = np.array([p["img_y"] for p in points], dtype=np.float64)
    exp_x = np.array([p["exp_x"] for p in points], dtype=np.float64)
    exp_y = np.array([p["exp_y"] for p in points], dtype=np.float64)

    # Fit exp_x = a_x * img_x + b_x using least squares
    A_x = np.vstack([img_x, np.ones(len(img_x))]).T
    result_x = np.linalg.lstsq(A_x, exp_x, rcond=None)
    a_x, b_x = result_x[0]

    # Fit exp_y = a_y * img_y + b_y using least squares
    A_y = np.vstack([img_y, np.ones(len(img_y))]).T
    result_y = np.linalg.lstsq(A_y, exp_y, rcond=None)
    a_y, b_y = result_y[0]

    return {"a_x": a_x, "b_x": b_x, "a_y": a_y, "b_y": b_y}


def apply_geometry_correction(image, points, offset_mode="ignore",
                              resample_method="Lanczos",
                              bg_color=(0, 0, 0, 0),
                              coeffs_override=None,
                              cancel_event=None):
    """Apply geometry correction to an image.

    Computes scaling coefficients from point pairs, then scales and
    optionally offsets the image based on the offset_mode.

    Args:
        image: PIL Image (RGB or RGBA).
        points: List of dicts with keys: img_x, img_y, exp_x, exp_y.
        offset_mode: One of 'ignore', 'shrink', 'expand', 'keep'.
            - ignore: Scale only, no offset applied.
            - shrink: Crop the image by the offset values.
            - expand: Move the image, retain resolution after scaling;
                      empty areas filled with bg_color.
            - keep: Similar to expand but retains original resolution.
        resample_method: Name of resampling method (key from RESAMPLE_METHODS).
        bg_color: Background color tuple (R, G, B, A) for filling empty areas.
        coeffs_override: Optional dict with keys a_x, b_x, a_y, b_y.
            If provided, these coefficients are used directly instead of
            computing them from points.
        cancel_event: Optional threading.Event for cancellation.

    Returns:
        Corrected PIL Image, or None if cancelled or insufficient points.
    """
    if coeffs_override is not None:
        coeffs = coeffs_override
    else:
        if len(points) < 2:
            return None
        coeffs = compute_geometry_coefficients(points)
        if coeffs is None:
            return None

    if cancel_event and cancel_event.is_set():
        return None

    a_x = coeffs["a_x"]
    b_x = coeffs["b_x"]
    a_y = coeffs["a_y"]
    b_y = coeffs["b_y"]

    # Avoid degenerate scaling
    if abs(a_x) < 1e-10 or abs(a_y) < 1e-10:
        return None

    src_w, src_h = image.size

    # The scaling factors
    scale_x = a_x
    scale_y = a_y

    # New dimensions after scaling
    new_w = max(1, int(round(src_w * scale_x)))
    new_h = max(1, int(round(src_h * scale_y)))

    resample = RESAMPLE_METHODS.get(resample_method, Image.LANCZOS)

    # Ensure RGBA for transparency support
    if image.mode != "RGBA":
        work_image = image.convert("RGBA")
    else:
        work_image = image.copy()

    if cancel_event and cancel_event.is_set():
        return None

    # Scale the image
    scaled = work_image.resize((new_w, new_h), resample)

    if cancel_event and cancel_event.is_set():
        return None

    if offset_mode == "ignore":
        # Just return the scaled image, no offset
        return scaled

    elif offset_mode == "shrink":
        # Crop the image by the offset values
        # b_x is the X offset in output space, b_y is the Y offset
        # Positive b means the image content starts further in, so we crop from that side
        crop_left = max(0, int(round(b_x)))
        crop_top = max(0, int(round(b_y)))
        crop_right = max(0, int(round(-b_x))) if b_x < 0 else 0
        crop_bottom = max(0, int(round(-b_y))) if b_y < 0 else 0

        # Ensure we don't crop more than the image
        crop_left = min(crop_left, new_w - 1)
        crop_top = min(crop_top, new_h - 1)
        crop_right = min(crop_right, new_w - crop_left - 1)
        crop_bottom = min(crop_bottom, new_h - crop_top - 1)

        result = scaled.crop((
            crop_left,
            crop_top,
            new_w - crop_right,
            new_h - crop_bottom
        ))
        return result

    elif offset_mode == "expand":
        # Move the image within the scaled resolution, fill empty with bg_color
        offset_x = int(round(b_x))
        offset_y = int(round(b_y))

        result = Image.new("RGBA", (new_w, new_h), bg_color)
        # Paste the scaled image at the offset position
        paste_x = offset_x
        paste_y = offset_y

        # We need to handle negative offsets (paste partially off-canvas)
        # by cropping the source before pasting
        src_crop_left = max(0, -paste_x)
        src_crop_top = max(0, -paste_y)
        src_crop_right = min(new_w, new_w - paste_x)
        src_crop_bottom = min(new_h, new_h - paste_y)

        dst_x = max(0, paste_x)
        dst_y = max(0, paste_y)

        if src_crop_left < new_w and src_crop_top < new_h:
            cropped_scaled = scaled.crop((
                src_crop_left, src_crop_top,
                min(new_w, src_crop_right),
                min(new_h, src_crop_bottom)
            ))
            result.paste(cropped_scaled, (dst_x, dst_y), cropped_scaled)

        return result

    elif offset_mode == "keep":
        # Similar to expand but retains original resolution
        offset_x = int(round(b_x))
        offset_y = int(round(b_y))

        result = Image.new("RGBA", (src_w, src_h), bg_color)

        # Paste the scaled image at the offset position within original dimensions
        paste_x = offset_x
        paste_y = offset_y

        src_crop_left = max(0, -paste_x)
        src_crop_top = max(0, -paste_y)
        src_crop_right = min(new_w, src_w - paste_x)
        src_crop_bottom = min(new_h, src_h - paste_y)

        dst_x = max(0, paste_x)
        dst_y = max(0, paste_y)

        if src_crop_left < new_w and src_crop_top < new_h and src_crop_right > src_crop_left and src_crop_bottom > src_crop_top:
            cropped_scaled = scaled.crop((
                src_crop_left, src_crop_top,
                src_crop_right,
                src_crop_bottom
            ))
            result.paste(cropped_scaled, (dst_x, dst_y), cropped_scaled)

        return result

    # Fallback
    return scaled
