"""Shared preview background color options.

The preview background is a global, viewer-only setting (selected from the
main toolbar). It affects how RGBA images are composited for display but is
never baked into the edited/saved image.
"""

# Predefined background colors for preview
BG_COLORS = {
    "White": (255, 255, 255),
    "Black": (0, 0, 0),
    "Red": (255, 0, 0),
    "Green": (0, 255, 0),
    "Blue": (0, 0, 255),
    "Magenta": (255, 0, 255),
    "Gray": (128, 128, 128),
}
