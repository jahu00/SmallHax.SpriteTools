"""Color correction processing: match colors from a source image to a reference image."""

import numpy as np
from PIL import Image


def apply_color_correction(source_image, pairs, cancel_event=None):
    """Apply color correction to source_image based on color pairs.

    Uses thin-plate spline interpolation in RGB space to build a smooth
    color mapping from the source sample points to the reference sample points,
    then applies it to every pixel in the source image.

    Args:
        source_image: PIL Image (the image to correct).
        pairs: list of dicts with keys:
            - src_x, src_y: pixel coordinates on the source image
            - ref_x, ref_y: pixel coordinates on the reference image
            - src_color: (r, g, b) tuple of the source pixel color
            - ref_color: (r, g, b) tuple of the reference pixel color
        cancel_event: threading.Event for cancellation.

    Returns:
        Corrected PIL Image (RGB), or None if cancelled.
    """
    if not pairs:
        return source_image.convert("RGB")

    src_colors = np.array([p["src_color"] for p in pairs], dtype=np.float64)  # (N, 3)
    ref_colors = np.array([p["ref_color"] for p in pairs], dtype=np.float64)  # (N, 3)

    n = len(pairs)

    if n == 1:
        # Simple offset correction
        offset = ref_colors[0] - src_colors[0]
        return _apply_offset(source_image, offset, cancel_event)

    # Build thin-plate spline (RBF) interpolation for each output channel
    # Using polyharmonic spline: phi(r) = r^2 * log(r) for 2D, but in color space
    # we use phi(r) = r (linear RBF) for simplicity and stability
    correction = _build_rbf_correction(src_colors, ref_colors)

    if cancel_event and cancel_event.is_set():
        return None

    # Apply to all pixels
    rgb_array = np.array(source_image.convert("RGB"), dtype=np.float64)  # (H, W, 3)
    height, width = rgb_array.shape[:2]
    pixels = rgb_array.reshape(-1, 3)  # (H*W, 3)

    # Process in chunks to allow cancellation and manage memory
    chunk_size = 200000
    result_pixels = np.empty_like(pixels)

    for start in range(0, pixels.shape[0], chunk_size):
        if cancel_event and cancel_event.is_set():
            return None
        end = min(start + chunk_size, pixels.shape[0])
        result_pixels[start:end] = correction(pixels[start:end])

    result_pixels = np.clip(result_pixels, 0, 255)
    result_array = result_pixels.reshape(height, width, 3).astype(np.uint8)

    return Image.fromarray(result_array, "RGB")


def _apply_offset(image, offset, cancel_event=None):
    """Apply a simple constant color offset to all pixels."""
    rgb_array = np.array(image.convert("RGB"), dtype=np.float64)

    if cancel_event and cancel_event.is_set():
        return None

    rgb_array += offset
    rgb_array = np.clip(rgb_array, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb_array, "RGB")


def _build_rbf_correction(src_colors, ref_colors):
    """Build an RBF-based color correction function.

    Uses linear RBF (phi(r) = r) with a polynomial term for affine correction.
    Solves for weights that map src_colors -> ref_colors, then returns a
    callable that applies the mapping to arbitrary pixel arrays.

    Args:
        src_colors: (N, 3) array of source RGB colors.
        ref_colors: (N, 3) array of target RGB colors.

    Returns:
        Callable that takes (M, 3) pixel array and returns (M, 3) corrected array.
    """
    n = src_colors.shape[0]

    # Build RBF matrix: phi(||src_i - src_j||)
    # Using linear kernel: phi(r) = r
    dists = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(n):
            dists[i, j] = np.sqrt(np.sum((src_colors[i] - src_colors[j]) ** 2))

    phi = dists  # linear RBF

    # Augmented system: [phi, P; P^T, 0] * [w; v] = [ref; 0]
    # P = [1, src_r, src_g, src_b] for affine term
    P = np.hstack([np.ones((n, 1)), src_colors])  # (N, 4)

    # Build system matrix
    A = np.zeros((n + 4, n + 4), dtype=np.float64)
    A[:n, :n] = phi
    A[:n, n:n + 4] = P
    A[n:n + 4, :n] = P.T

    # Add small regularization for numerical stability
    A[:n, :n] += np.eye(n) * 1e-4

    # Solve for each output channel
    weights = np.zeros((n + 4, 3), dtype=np.float64)
    for c in range(3):
        rhs = np.zeros(n + 4, dtype=np.float64)
        rhs[:n] = ref_colors[:, c]
        try:
            weights[:, c] = np.linalg.solve(A, rhs)
        except np.linalg.LinAlgError:
            # Fallback: least squares
            weights[:, c], _, _, _ = np.linalg.lstsq(A, rhs, rcond=None)

    w = weights[:n]   # (N, 3) RBF weights
    v = weights[n:]   # (4, 3) polynomial weights

    def correction(pixels):
        """Apply the RBF correction to an (M, 3) array of pixels."""
        m = pixels.shape[0]

        # Compute distances from each pixel to each source control point
        # pixels: (M, 3), src_colors: (N, 3)
        # dists: (M, N)
        diffs = pixels[:, np.newaxis, :] - src_colors[np.newaxis, :, :]  # (M, N, 3)
        d = np.sqrt(np.sum(diffs ** 2, axis=2))  # (M, N)

        # RBF contribution: sum_j w_j * phi(||pixel - src_j||)
        rbf_part = d @ w  # (M, 3)

        # Polynomial contribution: v0 + v1*r + v2*g + v3*b
        P_pixels = np.hstack([np.ones((m, 1)), pixels])  # (M, 4)
        poly_part = P_pixels @ v  # (M, 3)

        return rbf_part + poly_part

    return correction
