"""Sprite crop side panel UI with interactive handle dragging."""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from sprite_crop import compute_tile_rects, crop_tile, crop_all_tiles


# Handle hit-test radius in image pixels
_HANDLE_RADIUS = 8


class SpriteCropPanel:
    """Side panel for the sprite crop tool.

    Allows defining margins, grid rows/columns, and inner tile margins.
    Shows a preview of a selected tile and draws grid overlay on the image.
    Supports interactive dragging of outer margin handles and inner margin edges.
    """

    # Outer margin handle identifiers
    _HANDLE_TOP = "top"
    _HANDLE_BOTTOM = "bottom"
    _HANDLE_LEFT = "left"
    _HANDLE_RIGHT = "right"
    _HANDLE_TOP_LEFT = "top_left"
    _HANDLE_TOP_RIGHT = "top_right"
    _HANDLE_BOTTOM_LEFT = "bottom_left"
    _HANDLE_BOTTOM_RIGHT = "bottom_right"

    # Inner margin handle identifiers
    _HANDLE_INNER_H = "inner_h"
    _HANDLE_INNER_V = "inner_v"

    def __init__(self, parent_frame, on_apply, on_cancel, on_overlay_changed=None):
        """Initialize the panel.

        Args:
            parent_frame: Parent tk.Frame to build UI into.
            on_apply: Callback(cropped_image) when user applies crop.
            on_cancel: Callback() when user cancels.
            on_overlay_changed: Callback() when overlay parameters change (triggers re-render).
        """
        self.parent_frame = parent_frame
        self._on_apply = on_apply
        self._on_cancel = on_cancel
        self._on_overlay_changed = on_overlay_changed

        # State
        self._source_image = None
        self._preview_tk_image = None

        # Drag state
        self._active_handle = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_start_values = {}

        self._build_ui()

        # Register traces after UI is built
        for var in (self._margin_top_var, self._margin_bottom_var,
                    self._margin_left_var, self._margin_right_var,
                    self._rows_var, self._cols_var,
                    self._inner_h_var, self._inner_v_var,
                    self._tile_index_var):
            var.trace_add("write", lambda *_: self._on_params_changed())

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Sprite Crop", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # ─── Outer Margins ──────────────────────────────────────────────
        tk.Label(panel, text="Outer Margins:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        margin_frame = tk.Frame(panel)
        margin_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(margin_frame, text="Top:", font=("", 8)).grid(row=0, column=0, sticky=tk.W)
        self._margin_top_var = tk.IntVar(value=0)
        tk.Spinbox(margin_frame, from_=0, to=9999, width=5,
                   textvariable=self._margin_top_var).grid(row=0, column=1, padx=2)

        tk.Label(margin_frame, text="Bottom:", font=("", 8)).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        self._margin_bottom_var = tk.IntVar(value=0)
        tk.Spinbox(margin_frame, from_=0, to=9999, width=5,
                   textvariable=self._margin_bottom_var).grid(row=0, column=3, padx=2)

        tk.Label(margin_frame, text="Left:", font=("", 8)).grid(row=1, column=0, sticky=tk.W)
        self._margin_left_var = tk.IntVar(value=0)
        tk.Spinbox(margin_frame, from_=0, to=9999, width=5,
                   textvariable=self._margin_left_var).grid(row=1, column=1, padx=2)

        tk.Label(margin_frame, text="Right:", font=("", 8)).grid(row=1, column=2, sticky=tk.W, padx=(8, 0))
        self._margin_right_var = tk.IntVar(value=0)
        tk.Spinbox(margin_frame, from_=0, to=9999, width=5,
                   textvariable=self._margin_right_var).grid(row=1, column=3, padx=2)

        # ─── Grid Layout ────────────────────────────────────────────────
        sep1 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep1.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Grid Layout:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        grid_frame = tk.Frame(panel)
        grid_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(grid_frame, text="Rows:", font=("", 8)).pack(side=tk.LEFT)
        self._rows_var = tk.IntVar(value=1)
        tk.Spinbox(grid_frame, from_=1, to=100, width=4,
                   textvariable=self._rows_var).pack(side=tk.LEFT, padx=4)

        tk.Label(grid_frame, text="Cols:", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))
        self._cols_var = tk.IntVar(value=1)
        tk.Spinbox(grid_frame, from_=1, to=100, width=4,
                   textvariable=self._cols_var).pack(side=tk.LEFT, padx=4)

        # ─── Inner Margins ──────────────────────────────────────────────
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Inner Tile Margins:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        inner_frame = tk.Frame(panel)
        inner_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(inner_frame, text="Horizontal:", font=("", 8)).pack(side=tk.LEFT)
        self._inner_h_var = tk.IntVar(value=0)
        tk.Spinbox(inner_frame, from_=0, to=9999, width=5,
                   textvariable=self._inner_h_var).pack(side=tk.LEFT, padx=4)

        tk.Label(inner_frame, text="Vertical:", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))
        self._inner_v_var = tk.IntVar(value=0)
        tk.Spinbox(inner_frame, from_=0, to=9999, width=5,
                   textvariable=self._inner_v_var).pack(side=tk.LEFT, padx=4)

        # ─── Tile Info ──────────────────────────────────────────────────
        sep3 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep3.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._tile_info_var = tk.StringVar(value="Tile size: —")
        tk.Label(panel, textvariable=self._tile_info_var, font=("", 8), fg="gray").pack(
            padx=8, anchor=tk.W
        )

        # ─── Tile Preview ───────────────────────────────────────────────
        sep4 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep4.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Tile Preview:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        # Tile index slider
        slider_frame = tk.Frame(panel)
        slider_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(slider_frame, text="Tile #:", font=("", 8)).pack(side=tk.LEFT)
        self._tile_index_var = tk.IntVar(value=0)
        self._tile_slider = tk.Scale(
            slider_frame, from_=0, to=0, orient=tk.HORIZONTAL,
            variable=self._tile_index_var, showvalue=True
        )
        self._tile_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # Preview canvas (scales to fit panel width)
        self._preview_canvas = tk.Canvas(panel, height=150, bg="#3c3c3c", highlightthickness=0)
        self._preview_canvas.pack(fill=tk.X, padx=8, pady=4)

        # ─── Bottom Buttons ─────────────────────────────────────────────
        btn_frame = tk.Frame(panel)
        btn_frame.pack(fill=tk.X, padx=8, pady=8, side=tk.BOTTOM)

        tk.Button(btn_frame, text="Apply", command=self._apply).pack(
            side=tk.RIGHT, padx=2
        )
        tk.Button(btn_frame, text="Cancel", command=self._cancel).pack(
            side=tk.RIGHT, padx=2
        )

    # ─── Public Interface ───────────────────────────────────────────────

    def set_source_image(self, image):
        """Set the source image to crop."""
        self._source_image = image
        self._on_params_changed()

    def reset(self):
        """Reset all state to defaults."""
        self._source_image = None
        self._margin_top_var.set(0)
        self._margin_bottom_var.set(0)
        self._margin_left_var.set(0)
        self._margin_right_var.set(0)
        self._rows_var.set(1)
        self._cols_var.set(1)
        self._inner_h_var.set(0)
        self._inner_v_var.set(0)
        self._tile_index_var.set(0)
        self._tile_slider.config(to=0)
        self._tile_info_var.set("Tile size: —")
        self._preview_canvas.delete("all")
        self._preview_tk_image = None
        self._active_handle = None

    def get_grid_params(self):
        """Return current grid parameters as a dict."""
        try:
            margin_top = max(0, self._margin_top_var.get())
            margin_bottom = max(0, self._margin_bottom_var.get())
            margin_left = max(0, self._margin_left_var.get())
            margin_right = max(0, self._margin_right_var.get())
            rows = max(1, self._rows_var.get())
            cols = max(1, self._cols_var.get())
            inner_h = max(0, self._inner_h_var.get())
            inner_v = max(0, self._inner_v_var.get())
        except (tk.TclError, ValueError):
            return None

        return {
            "margin_top": margin_top,
            "margin_bottom": margin_bottom,
            "margin_left": margin_left,
            "margin_right": margin_right,
            "rows": rows,
            "cols": cols,
            "inner_h": inner_h,
            "inner_v": inner_v,
        }

    def get_tile_rects(self):
        """Compute tile rectangles based on current parameters.

        Returns a list of (x, y, w, h) tuples in image coordinates,
        or None if parameters are invalid.
        """
        if self._source_image is None:
            return None

        params = self.get_grid_params()
        if params is None:
            return None

        img_w, img_h = self._source_image.size

        return compute_tile_rects(
            img_w, img_h,
            params["margin_top"], params["margin_bottom"],
            params["margin_left"], params["margin_right"],
            params["rows"], params["cols"],
            params["inner_h"], params["inner_v"],
        )

    # ─── Interactive Handle Dragging ────────────────────────────────────

    def on_mouse_press(self, img_x, img_y):
        """Handle mouse press — detect which handle is being grabbed."""
        self._active_handle = self._hit_test(img_x, img_y)
        if self._active_handle:
            self._drag_start_x = img_x
            self._drag_start_y = img_y
            self._drag_start_values = {
                "margin_top": self._margin_top_var.get(),
                "margin_bottom": self._margin_bottom_var.get(),
                "margin_left": self._margin_left_var.get(),
                "margin_right": self._margin_right_var.get(),
                "inner_h": self._inner_h_var.get(),
                "inner_v": self._inner_v_var.get(),
            }

    def on_mouse_drag(self, img_x, img_y):
        """Handle mouse drag — update the value for the active handle."""
        if not self._active_handle or self._source_image is None:
            return

        dx = img_x - self._drag_start_x
        dy = img_y - self._drag_start_y

        img_w, img_h = self._source_image.size
        max_inner_h = img_w // 2 - 1
        max_inner_v = img_h // 2 - 1

        handle = self._active_handle
        sv = self._drag_start_values

        if handle == self._HANDLE_TOP:
            new_val = max(0, sv["margin_top"] + dy)
            self._margin_top_var.set(int(new_val))
        elif handle == self._HANDLE_BOTTOM:
            new_val = max(0, sv["margin_bottom"] - dy)
            self._margin_bottom_var.set(int(new_val))
        elif handle == self._HANDLE_LEFT:
            new_val = max(0, sv["margin_left"] + dx)
            self._margin_left_var.set(int(new_val))
        elif handle == self._HANDLE_RIGHT:
            new_val = max(0, sv["margin_right"] - dx)
            self._margin_right_var.set(int(new_val))
        elif handle == self._HANDLE_TOP_LEFT:
            self._margin_top_var.set(int(max(0, sv["margin_top"] + dy)))
            self._margin_left_var.set(int(max(0, sv["margin_left"] + dx)))
        elif handle == self._HANDLE_TOP_RIGHT:
            self._margin_top_var.set(int(max(0, sv["margin_top"] + dy)))
            self._margin_right_var.set(int(max(0, sv["margin_right"] - dx)))
        elif handle == self._HANDLE_BOTTOM_LEFT:
            self._margin_bottom_var.set(int(max(0, sv["margin_bottom"] - dy)))
            self._margin_left_var.set(int(max(0, sv["margin_left"] + dx)))
        elif handle == self._HANDLE_BOTTOM_RIGHT:
            self._margin_bottom_var.set(int(max(0, sv["margin_bottom"] - dy)))
            self._margin_right_var.set(int(max(0, sv["margin_right"] - dx)))
        elif handle == self._HANDLE_INNER_H:
            new_val = min(max_inner_h, abs(sv["inner_h"] + dx))
            self._inner_h_var.set(int(new_val))
        elif handle == self._HANDLE_INNER_V:
            new_val = min(max_inner_v, abs(sv["inner_v"] + dy))
            self._inner_v_var.set(int(new_val))

    def _hit_test(self, img_x, img_y):
        """Determine which handle (if any) is at the given image coordinates.

        Priority: corners > edges > inner margins.
        Returns a handle identifier string or None.
        """
        if self._source_image is None:
            return None

        params = self.get_grid_params()
        if params is None:
            return None

        img_w, img_h = self._source_image.size
        r = _HANDLE_RADIUS

        # Content area edges
        left = params["margin_left"]
        top = params["margin_top"]
        right = img_w - params["margin_right"]
        bottom = img_h - params["margin_bottom"]
        mid_x = (left + right) / 2
        mid_y = (top + bottom) / 2

        # Check corners first
        if abs(img_x - left) <= r and abs(img_y - top) <= r:
            return self._HANDLE_TOP_LEFT
        if abs(img_x - right) <= r and abs(img_y - top) <= r:
            return self._HANDLE_TOP_RIGHT
        if abs(img_x - left) <= r and abs(img_y - bottom) <= r:
            return self._HANDLE_BOTTOM_LEFT
        if abs(img_x - right) <= r and abs(img_y - bottom) <= r:
            return self._HANDLE_BOTTOM_RIGHT

        # Check edge midpoints
        if abs(img_x - mid_x) <= r and abs(img_y - top) <= r:
            return self._HANDLE_TOP
        if abs(img_x - mid_x) <= r and abs(img_y - bottom) <= r:
            return self._HANDLE_BOTTOM
        if abs(img_x - left) <= r and abs(img_y - mid_y) <= r:
            return self._HANDLE_LEFT
        if abs(img_x - right) <= r and abs(img_y - mid_y) <= r:
            return self._HANDLE_RIGHT

        # Check inner margin edges — test against the first tile's inner boundary
        # For inner_h: the left edge of the first tile (content_x + inner_h)
        # For inner_v: the top edge of the first tile (content_y + inner_v)
        inner_h = params["inner_h"]
        inner_v = params["inner_v"]

        content_w = right - left
        content_h = bottom - top
        if content_w <= 0 or content_h <= 0:
            return None

        rows = params["rows"]
        cols = params["cols"]

        total_margin_h = inner_h * 2 * cols
        total_margin_v = inner_v * 2 * rows

        tile_w = (content_w - total_margin_h) / cols
        tile_h = (content_h - total_margin_v) / rows

        if tile_w <= 0 or tile_h <= 0:
            return None

        cell_w = tile_w + inner_h * 2
        cell_h = tile_h + inner_v * 2

        # Check if click is near any vertical inner margin edge (left side of any tile)
        if inner_h > 0 or True:  # always allow grabbing even at 0
            for col in range(cols):
                edge_x = left + col * cell_w + inner_h  # left edge of tile
                if abs(img_x - edge_x) <= r and top <= img_y <= bottom:
                    return self._HANDLE_INNER_H
                # Right edge of tile
                edge_x2 = left + col * cell_w + inner_h + tile_w
                if abs(img_x - edge_x2) <= r and top <= img_y <= bottom:
                    return self._HANDLE_INNER_H

        # Check if click is near any horizontal inner margin edge (top side of any tile)
        if inner_v > 0 or True:  # always allow grabbing even at 0
            for row in range(rows):
                edge_y = top + row * cell_h + inner_v  # top edge of tile
                if abs(img_y - edge_y) <= r and left <= img_x <= right:
                    return self._HANDLE_INNER_V
                # Bottom edge of tile
                edge_y2 = top + row * cell_h + inner_v + tile_h
                if abs(img_y - edge_y2) <= r and left <= img_x <= right:
                    return self._HANDLE_INNER_V

        return None

    # ─── Overlay Drawing ────────────────────────────────────────────────

    def draw_overlay(self, canvas, draw_x, draw_y, zoom_level):
        """Draw grid lines, tile center crosses, and drag handles on the canvas."""
        if self._source_image is None:
            return

        params = self.get_grid_params()
        if params is None:
            return

        img_w, img_h = self._source_image.size

        # Content area
        content_x = params["margin_left"]
        content_y = params["margin_top"]
        content_w = img_w - params["margin_left"] - params["margin_right"]
        content_h = img_h - params["margin_top"] - params["margin_bottom"]

        if content_w <= 0 or content_h <= 0:
            return

        rows = params["rows"]
        cols = params["cols"]
        inner_h = params["inner_h"]
        inner_v = params["inner_v"]

        total_margin_h = inner_h * 2 * cols
        total_margin_v = inner_v * 2 * rows

        tile_w = (content_w - total_margin_h) / cols
        tile_h = (content_h - total_margin_v) / rows

        if tile_w <= 0 or tile_h <= 0:
            return

        cell_w = tile_w + inner_h * 2
        cell_h = tile_h + inner_v * 2

        # Helper to convert image coords to canvas coords
        def to_canvas(ix, iy):
            cx = draw_x + ix * zoom_level
            cy = draw_y + iy * zoom_level
            return cx, cy

        # Draw outer margin boundary (content area rectangle)
        cx0, cy0 = to_canvas(content_x, content_y)
        cx1, cy1 = to_canvas(content_x + content_w, content_y + content_h)
        canvas.create_rectangle(cx0, cy0, cx1, cy1, outline="#ff8800", width=1, dash=(4, 4))

        # Draw tile boundaries and center crosses
        for row in range(rows):
            for col in range(cols):
                tx = content_x + col * cell_w + inner_h
                ty = content_y + row * cell_h + inner_v

                # Tile rectangle
                tcx0, tcy0 = to_canvas(tx, ty)
                tcx1, tcy1 = to_canvas(tx + tile_w, ty + tile_h)
                canvas.create_rectangle(tcx0, tcy0, tcx1, tcy1,
                                        outline="#ffff00", width=1, dash=(2, 2))

                # Center cross
                cross_size = max(3, min(tile_w, tile_h) * 0.1)
                center_x = tx + tile_w / 2
                center_y = ty + tile_h / 2
                ccx, ccy = to_canvas(center_x, center_y)
                cs = cross_size * zoom_level

                canvas.create_line(ccx - cs, ccy, ccx + cs, ccy,
                                   fill="#00ff00", width=1)
                canvas.create_line(ccx, ccy - cs, ccx, ccy + cs,
                                   fill="#00ff00", width=1)

        # ─── Draw drag handles ──────────────────────────────────────────
        handle_size = 5  # pixels on screen

        # Outer margin handles: corners and edge midpoints
        right_edge = content_x + content_w
        bottom_edge = content_y + content_h
        mid_x = content_x + content_w / 2
        mid_y = content_y + content_h / 2

        handle_positions = [
            (content_x, content_y),          # top-left
            (right_edge, content_y),         # top-right
            (content_x, bottom_edge),        # bottom-left
            (right_edge, bottom_edge),       # bottom-right
            (mid_x, content_y),              # top-mid
            (mid_x, bottom_edge),            # bottom-mid
            (content_x, mid_y),              # left-mid
            (right_edge, mid_y),             # right-mid
        ]

        for hx, hy in handle_positions:
            cx, cy = to_canvas(hx, hy)
            canvas.create_rectangle(
                cx - handle_size, cy - handle_size,
                cx + handle_size, cy + handle_size,
                fill="#ff8800", outline="#ffffff", width=1
            )

    # ─── Internal ───────────────────────────────────────────────────────

    def _on_params_changed(self):
        """Called when any parameter changes."""
        self._update_tile_info()
        self._update_slider_range()
        self._update_preview()
        if self._on_overlay_changed:
            self._on_overlay_changed()

    def _update_tile_info(self):
        """Update the tile size info label."""
        rects = self.get_tile_rects()
        if rects and len(rects) > 0:
            _, _, tw, th = rects[0]
            self._tile_info_var.set(f"Tile size: {tw:.1f} × {th:.1f} px")
        else:
            self._tile_info_var.set("Tile size: —")

    def _update_slider_range(self):
        """Update the tile index slider range."""
        rects = self.get_tile_rects()
        if rects:
            max_idx = len(rects) - 1
            self._tile_slider.config(to=max_idx)
            try:
                current = self._tile_index_var.get()
                if current > max_idx:
                    self._tile_index_var.set(max_idx)
            except tk.TclError:
                self._tile_index_var.set(0)
        else:
            self._tile_slider.config(to=0)
            self._tile_index_var.set(0)

    def _update_preview(self):
        """Update the tile preview canvas."""
        self._preview_canvas.delete("all")
        self._preview_tk_image = None

        if self._source_image is None:
            return

        rects = self.get_tile_rects()
        if not rects:
            return

        try:
            idx = self._tile_index_var.get()
        except tk.TclError:
            idx = 0

        if idx < 0 or idx >= len(rects):
            idx = 0

        tile_img = crop_tile(self._source_image, rects, idx)
        if tile_img is None:
            return

        # Scale to fit the preview canvas width
        canvas_w = self._preview_canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 260  # fallback

        scale = canvas_w / tile_img.width if tile_img.width > 0 else 1
        preview_h = int(tile_img.height * scale)
        if preview_h <= 0:
            preview_h = 1

        # Cap height
        max_h = 200
        if preview_h > max_h:
            scale = max_h / tile_img.height
            preview_h = max_h

        preview_w = int(tile_img.width * scale)
        if preview_w <= 0:
            preview_w = 1

        resample = Image.LANCZOS if scale < 1.0 else Image.NEAREST
        preview_img = tile_img.resize((preview_w, preview_h), resample)

        # Handle RGBA
        if preview_img.mode == "RGBA":
            bg = Image.new("RGB", (preview_w, preview_h), (60, 60, 60))
            bg.paste(preview_img, mask=preview_img.split()[3])
            preview_img = bg

        self._preview_canvas.config(height=preview_h)
        self._preview_tk_image = ImageTk.PhotoImage(preview_img)
        self._preview_canvas.create_image(0, 0, anchor=tk.NW, image=self._preview_tk_image)

    # ─── Apply / Cancel ─────────────────────────────────────────────────

    def _apply(self):
        """Crop all tiles and reconstruct into a single image."""
        if self._source_image is None:
            self._cancel()
            return

        rects = self.get_tile_rects()
        if not rects:
            self._cancel()
            return

        params = self.get_grid_params()
        if params is None:
            self._cancel()
            return

        result = crop_all_tiles(
            self._source_image, rects, params["rows"], params["cols"]
        )
        if result is None:
            self._cancel()
            return

        self._on_apply(result)

    def _cancel(self):
        """Cancel and return to cursor tool."""
        self._on_cancel()
