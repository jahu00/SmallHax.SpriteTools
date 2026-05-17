"""Reusable image viewer widget with zoom and pan support."""

import tkinter as tk
from PIL import Image, ImageTk
import math


# ─── Checkerboard Pattern ───────────────────────────────────────────────────

_checker_tile = None
_checker_tile_size = 8


def get_checker_tile(square_size=8):
    """Get or create a cached checkerboard tile."""
    global _checker_tile, _checker_tile_size
    if _checker_tile is None or _checker_tile_size != square_size:
        _checker_tile_size = square_size
        tile_size = square_size * 2
        tile = Image.new("RGB", (tile_size, tile_size))
        pixels = tile.load()
        for y in range(tile_size):
            for x in range(tile_size):
                if (x // square_size + y // square_size) % 2 == 0:
                    pixels[x, y] = (200, 200, 200)
                else:
                    pixels[x, y] = (255, 255, 255)
        _checker_tile = tile
    return _checker_tile


def create_checkerboard(width, height, square_size=8):
    """Create a checkerboard pattern image by tiling a small pattern."""
    tile = get_checker_tile(square_size)
    tile_w, tile_h = tile.size
    img = Image.new("RGB", (width, height))
    for y in range(0, height, tile_h):
        for x in range(0, width, tile_w):
            img.paste(tile, (x, y))
    return img


# ─── Image Viewer Widget ────────────────────────────────────────────────────

class ImageViewer(tk.Frame):
    """A reusable image viewer widget with zoom, pan, and overlay support.

    This widget displays a single image with:
    - Zoom via Ctrl+scroll
    - Pan via middle-mouse drag or left-click drag (when in pan mode)
    - Configurable left-click behavior via callbacks
    - Overlay rendering via a draw callback
    - RGBA compositing over checkerboard or solid background
    """

    def __init__(self, parent, bg_color_func=None, **kwargs):
        """Initialize the ImageViewer.

        Args:
            parent: Parent Tkinter widget.
            bg_color_func: Optional callable returning an (r, g, b) tuple for
                solid background compositing, or None for checkerboard.
            **kwargs: Additional keyword arguments passed to tk.Frame.
        """
        super().__init__(parent, **kwargs)

        self._bg_color_func = bg_color_func

        # Image state
        self._image = None
        self._zoom_level = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._tk_image = None

        # Pan state
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._pan_start_offset_x = 0
        self._pan_start_offset_y = 0

        # Callbacks
        self._on_left_click = None
        self._on_left_drag = None
        self._on_draw_overlay = None
        self._on_zoom_changed = None

        # Enable left-click panning by default
        self._left_click_pans = True

        # Build canvas
        self._canvas = tk.Canvas(self, bg="#3c3c3c", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._bind_events()

    # ─── Public Properties ──────────────────────────────────────────────

    @property
    def canvas(self):
        """Access the underlying canvas (for drag-and-drop registration etc.)."""
        return self._canvas

    @property
    def image(self):
        """The currently displayed source image."""
        return self._image

    @image.setter
    def image(self, img):
        """Set the image to display and re-render."""
        self._image = img
        self.render()

    @property
    def zoom_level(self):
        """Current zoom level."""
        return self._zoom_level

    @zoom_level.setter
    def zoom_level(self, value):
        self._zoom_level = max(0.05, min(value, 50.0))
        if self._on_zoom_changed:
            self._on_zoom_changed(self._zoom_level)

    @property
    def offset_x(self):
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value):
        self._offset_x = value

    @property
    def offset_y(self):
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value):
        self._offset_y = value

    # ─── Public Configuration ───────────────────────────────────────────

    def set_left_click_pans(self, enabled):
        """Enable or disable left-click panning (default: True)."""
        self._left_click_pans = enabled

    def set_on_left_click(self, callback):
        """Set callback for left-click: callback(img_x, img_y, event)."""
        self._on_left_click = callback

    def set_on_left_drag(self, callback):
        """Set callback for left-drag: callback(img_x, img_y, event)."""
        self._on_left_drag = callback

    def set_on_draw_overlay(self, callback):
        """Set callback for drawing overlays after the image renders.

        callback(canvas, draw_x, draw_y, zoom_level)
        """
        self._on_draw_overlay = callback

    def set_on_zoom_changed(self, callback):
        """Set callback for zoom level changes: callback(zoom_level)."""
        self._on_zoom_changed = callback

    def set_bg_color_func(self, func):
        """Set the background color function for RGBA compositing."""
        self._bg_color_func = func

    # ─── Public Methods ─────────────────────────────────────────────────

    def fit_image(self):
        """Fit the current image to the canvas size."""
        if self._image is None:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = 800, 600

        iw, ih = self._image.size
        scale_x = cw / iw
        scale_y = ch / ih
        self._zoom_level = min(scale_x, scale_y, 1.0)
        self._offset_x = 0
        self._offset_y = 0
        if self._on_zoom_changed:
            self._on_zoom_changed(self._zoom_level)
        self.render()

    def reset_zoom(self):
        """Reset zoom to 100% and center the image."""
        if self._image is None:
            return
        if self._zoom_level == 1.0:
            self.fit_image()
        else:
            self._zoom_level = 1.0
            self._offset_x = 0
            self._offset_y = 0
            if self._on_zoom_changed:
                self._on_zoom_changed(self._zoom_level)
            self.render()

    def canvas_to_image_coords(self, canvas_x, canvas_y):
        """Convert canvas coordinates to image pixel coordinates.

        Returns (img_x, img_y) or None if outside the image bounds.
        """
        if self._image is None:
            return None

        draw_x = self._get_draw_offset_x()
        draw_y = self._get_draw_offset_y()

        img_x = int((canvas_x - draw_x) / self._zoom_level)
        img_y = int((canvas_y - draw_y) / self._zoom_level)

        w, h = self._image.size
        if img_x < 0 or img_x >= w or img_y < 0 or img_y >= h:
            return None

        return (img_x, img_y)

    def render(self):
        """Render the image onto the canvas (visible portion only)."""
        self._canvas.delete("all")

        if self._image is None:
            return

        iw, ih = self._image.size
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()

        if cw <= 1 or ch <= 1:
            return

        draw_x = self._get_draw_offset_x()
        draw_y = self._get_draw_offset_y()

        # Visible region intersection
        img_canvas_right = draw_x + iw * self._zoom_level
        img_canvas_bottom = draw_y + ih * self._zoom_level

        crop_canvas_left = max(0, draw_x)
        crop_canvas_top = max(0, draw_y)
        crop_canvas_right = min(cw, img_canvas_right)
        crop_canvas_bottom = min(ch, img_canvas_bottom)

        if crop_canvas_left >= crop_canvas_right or crop_canvas_top >= crop_canvas_bottom:
            return

        # Convert to source image coordinates
        src_left = max(0, int((crop_canvas_left - draw_x) / self._zoom_level))
        src_top = max(0, int((crop_canvas_top - draw_y) / self._zoom_level))
        src_right = min(iw, int(math.ceil((crop_canvas_right - draw_x) / self._zoom_level)))
        src_bottom = min(ih, int(math.ceil((crop_canvas_bottom - draw_y) / self._zoom_level)))

        if src_right <= src_left or src_bottom <= src_top:
            return

        cropped = self._image.crop((src_left, src_top, src_right, src_bottom))

        out_w = max(1, int((src_right - src_left) * self._zoom_level))
        out_h = max(1, int((src_bottom - src_top) * self._zoom_level))

        resample = Image.LANCZOS if self._zoom_level < 1.0 else Image.NEAREST
        resized = cropped.resize((out_w, out_h), resample)

        # Composite RGBA over checkerboard or solid background
        if resized.mode == "RGBA":
            bg_color = self._bg_color_func() if self._bg_color_func else None
            if bg_color is not None:
                bg = Image.new("RGB", (out_w, out_h), bg_color)
            else:
                bg = create_checkerboard(out_w, out_h)
            bg.paste(resized, mask=resized.split()[3])
            resized = bg

        self._tk_image = ImageTk.PhotoImage(resized)

        place_x = draw_x + src_left * self._zoom_level
        place_y = draw_y + src_top * self._zoom_level
        self._canvas.create_image(place_x, place_y, anchor=tk.NW, image=self._tk_image)

        # Draw overlays
        if self._on_draw_overlay:
            self._on_draw_overlay(self._canvas, draw_x, draw_y, self._zoom_level)

    # ─── Event Bindings ─────────────────────────────────────────────────

    def _bind_events(self):
        # Zoom (Ctrl + scroll)
        self._canvas.bind("<Control-Button-4>", self._on_zoom_in)
        self._canvas.bind("<Control-Button-5>", self._on_zoom_out)

        # Middle mouse pan
        self._canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self._canvas.bind("<B2-Motion>", self._on_pan_motion)

        # Left click / drag
        self._canvas.bind("<ButtonPress-1>", self._on_left_press)
        self._canvas.bind("<B1-Motion>", self._on_left_motion)

        # Redraw on resize
        self._canvas.bind("<Configure>", lambda e: self.render())

    # ─── Zoom ───────────────────────────────────────────────────────────

    def _on_zoom_in(self, event):
        self._apply_zoom(event, factor=1.15)

    def _on_zoom_out(self, event):
        self._apply_zoom(event, factor=1 / 1.15)

    def _apply_zoom(self, event, factor):
        if self._image is None:
            return

        old_zoom = self._zoom_level
        new_zoom = old_zoom * factor
        new_zoom = max(0.05, min(new_zoom, 50.0))

        canvas_x = self._canvas.canvasx(event.x)
        canvas_y = self._canvas.canvasy(event.y)

        img_x = (canvas_x - self._get_draw_offset_x(old_zoom)) / old_zoom
        img_y = (canvas_y - self._get_draw_offset_y(old_zoom)) / old_zoom

        new_draw_x = canvas_x - img_x * new_zoom
        new_draw_y = canvas_y - img_y * new_zoom

        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        iw = self._image.width * new_zoom
        ih = self._image.height * new_zoom

        self._offset_x = new_draw_x - (cw - iw) / 2
        self._offset_y = new_draw_y - (ch - ih) / 2
        self._zoom_level = new_zoom

        if self._on_zoom_changed:
            self._on_zoom_changed(self._zoom_level)
        self.render()

    # ─── Pan ────────────────────────────────────────────────────────────

    def _on_pan_start(self, event):
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._pan_start_offset_x = self._offset_x
        self._pan_start_offset_y = self._offset_y

    def _on_pan_motion(self, event):
        if self._image is None:
            return
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y
        self._offset_x = self._pan_start_offset_x + dx
        self._offset_y = self._pan_start_offset_y + dy
        self.render()

    # ─── Left Click / Drag ──────────────────────────────────────────────

    def _on_left_press(self, event):
        if self._left_click_pans:
            # Pan mode
            self._pan_start_x = event.x
            self._pan_start_y = event.y
            self._pan_start_offset_x = self._offset_x
            self._pan_start_offset_y = self._offset_y
        elif self._on_left_click:
            coords = self.canvas_to_image_coords(event.x, event.y)
            if coords:
                self._on_left_click(coords[0], coords[1], event)

    def _on_left_motion(self, event):
        if self._left_click_pans:
            if self._image is None:
                return
            dx = event.x - self._pan_start_x
            dy = event.y - self._pan_start_y
            self._offset_x = self._pan_start_offset_x + dx
            self._offset_y = self._pan_start_offset_y + dy
            self.render()
        elif self._on_left_drag:
            coords = self.canvas_to_image_coords(event.x, event.y)
            if coords:
                self._on_left_drag(coords[0], coords[1], event)

    # ─── Internal Helpers ───────────────────────────────────────────────

    def _get_draw_offset_x(self, zoom=None):
        if self._image is None:
            return 0
        if zoom is None:
            zoom = self._zoom_level
        cw = self._canvas.winfo_width()
        iw = self._image.width * zoom
        return (cw - iw) / 2 + self._offset_x

    def _get_draw_offset_y(self, zoom=None):
        if self._image is None:
            return 0
        if zoom is None:
            zoom = self._zoom_level
        ch = self._canvas.winfo_height()
        ih = self._image.height * zoom
        return (ch - ih) / 2 + self._offset_y
