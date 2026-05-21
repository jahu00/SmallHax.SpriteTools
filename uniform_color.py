"""Uniform color processing logic.

Similar to background removal but instead of making pixels transparent,
replaces them with the averaged color of the masked region. Each point's
mask is processed independently — each gets its own uniform color.
Border pixels (outside blend threshold) get a blended transition between
the original color and the new uniform color.
"""

import numpy as np
from PIL import Image

from bg_removal import (
    create_magic_wand_mask,
    feather_mask,
    compute_distance,
)


def process_uniform_color(image, points, blend_threshold, distance_metric="RGB",
                          blend_border=True, cancel_event=None):
    """Replace masked regions with their per-mask averaged color.

    Each point produces its own flood-fill mask. The average color is computed
    independently for each mask, and pixels within that mask are replaced
    with that mask's average. Border pixels (distance > blend_threshold from
    the seed color) get a smooth blend if blend_border is enabled, otherwise
    they are left unchanged.

    Args:
        image: PIL Image (RGB or RGBA).
        points: List of dicts {x, y, threshold, feathering}.
        blend_threshold: Distance below which pixels are fully replaced.
            Pixels beyond this get a gradual blend (if blend_border=True).
        distance_metric: 'RGB' or 'LAB' for distance computation.
        blend_border: If True, pixels outside blend_threshold get a smooth
            blend. If False, only pixels within threshold are replaced.
        cancel_event: Optional threading.Event for cancellation.

    Returns:
        PIL Image with uniform color applied, or None if cancelled.
    """
    if not points:
        return image.copy()

    # Work in RGB
    has_alpha = image.mode == "RGBA"
    rgb_image = image.convert("RGB")
    rgb_array = np.array(rgb_image).astype(np.float64)  # (H, W, 3)
    height, width = rgb_array.shape[:2]

    if has_alpha:
        alpha_channel = np.array(image.split()[3])
    else:
        alpha_channel = None

    result_rgb = rgb_array.copy()

    # Process each point's mask independently
    for pt in points:
        if cancel_event and cancel_event.is_set():
            return None

        # Get the raw flood-fill mask (before feathering) for averaging
        raw_mask = create_magic_wand_mask(
            rgb_array.astype(np.uint8), (pt["x"], pt["y"]), pt["threshold"],
            cancel_event
        )
        if raw_mask is None:
            return None

        # Apply feathering to get the full replacement region
        pt_mask = feather_mask(raw_mask, pt["feathering"])

        if cancel_event and cancel_event.is_set():
            return None

        # Get seed color for this point
        px, py = pt["x"], pt["y"]
        if px < 0 or px >= width or py < 0 or py >= height:
            continue
        seed_color = rgb_array[py, px]  # (3,)

        # Compute average color:
        # - If feathering is negative (erode), use the eroded mask (which is pt_mask)
        # - Otherwise use the raw (unfeathered) mask
        if pt["feathering"] < 0:
            avg_mask = pt_mask
        else:
            avg_mask = raw_mask

        avg_indices = np.where(avg_mask)
        if avg_indices[0].size == 0:
            continue
        avg_pixels = rgb_array[avg_indices[0], avg_indices[1]]
        avg_color = avg_pixels.mean(axis=0)  # (3,)

        # Get pixels in the full (feathered) mask for replacement
        mask_indices = np.where(pt_mask)
        if mask_indices[0].size == 0:
            continue

        masked_pixels = rgb_array[mask_indices[0], mask_indices[1]]  # (M, 3)

        # Compute distances from each masked pixel to the seed color
        distances = compute_distance(masked_pixels, seed_color, distance_metric)

        # Pixels within blend threshold: fully replaced with average color
        fully_replaced = distances <= blend_threshold

        # Pixels outside blend threshold: blend between original and average
        partial = ~fully_replaced

        # Fully replaced pixels
        if np.any(fully_replaced):
            fr_rows = mask_indices[0][fully_replaced]
            fr_cols = mask_indices[1][fully_replaced]
            result_rgb[fr_rows, fr_cols] = avg_color

        # Partial blend pixels
        if np.any(partial) and blend_border:
            p_rows = mask_indices[0][partial]
            p_cols = mask_indices[1][partial]
            p_pixels = masked_pixels[partial]  # (P, 3)
            p_distances = distances[partial]  # (P,)

            # Max possible distance for normalization
            max_dist = 441.67 if distance_metric == "RGB" else 375.0

            # Blend factor: 1.0 at blend_threshold, 0.0 at max_dist
            # Using sqrt for gentler falloff
            normalized = np.clip(
                (p_distances - blend_threshold) / (max_dist - blend_threshold + 1e-10),
                0, 1
            )
            blend_factor = 1.0 - np.sqrt(normalized)  # 1 = full replacement, 0 = original

            # Blend: result = original * (1 - factor) + avg_color * factor
            blended = np.zeros_like(p_pixels)
            for c in range(3):
                blended[:, c] = p_pixels[:, c] * (1 - blend_factor) + avg_color[c] * blend_factor

            result_rgb[p_rows, p_cols] = np.clip(blended, 0, 255)

    if cancel_event and cancel_event.is_set():
        return None

    # Assemble output
    result_u8 = result_rgb.clip(0, 255).astype(np.uint8)

    if has_alpha:
        out = Image.fromarray(result_u8, "RGB").convert("RGBA")
        out.putalpha(Image.fromarray(alpha_channel))
        return out
    else:
        return Image.fromarray(result_u8, "RGB")
