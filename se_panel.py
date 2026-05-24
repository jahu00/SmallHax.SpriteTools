"""Sprite edit side panel UI.

Allows defining tile size, grid rows/columns, per-tile flip options,
and output rows/columns for reassembly.
"""

import math
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from sprite_edit import compute_tile_rects, crop_tile, apply_tile_flips, reassemble_tiles


class SpriteEditPanel:
    """Side panel for the sprite edit tool.

    The user defines input rows/columns — tile size is computed automatically
    from the image dimensions. A checkbox unlocks manual tile size override.
    For each tile, horizontal and/or vertical flip can be toggled.
    The output image can have a different number of rows/columns.
    """

    def __init__(self, parent_frame, on_apply, on_cancel, on_overlay_changed=None,
                 on_preview_changed=None):
        """Initialize the panel.

        Args:
            parent_frame: Parent tk.Frame to build UI into.
            on_apply: Callback(result_image) when user applies.
            on_cancel: Callback() when user cancels.
            on_overlay_changed: Callback() when overlay parameters change.
            on_preview_changed: Callback(image_or_None) when preview toggle/content changes.
        """
        self.parent_frame = parent_frame
        self._on_apply = on_apply
        self._on_cancel = on_cancel
        self._on_overlay_changed = on_overlay_changed
        self._on_preview_changed = on_preview_changed

        # State
        self._source_image = None
        self._preview_tk_image = None

        # Per-tile flip state: sets of tile indices
        self._flip_h_set = set()
        self._flip_v_set = set()

        # Flag to suppress recursive trace callbacks
        self._suppress_params_changed = False

        self._build_ui()

        # Register traces after UI is built
        for var in (self._rows_var, self._cols_var,
                    self._tile_index_var):
            var.trace_add("write", lambda *_: self._on_params_changed())

        self._tile_w_var.trace_add("write", lambda *_: self._on_tile_size_changed())
        self._tile_h_var.trace_add("write", lambda *_: self._on_tile_size_changed())
        self._out_rows_var.trace_add("write", lambda *_: self._on_params_changed())
        self._out_cols_var.trace_add("write", lambda *_: self._on_params_changed())

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Sprite Edit", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # ─── Input Grid Layout ──────────────────────────────────────────
        tk.Label(panel, text="Input Grid:", font=("", 10)).pack(
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

        # ─── Tile Size (auto-computed, unlockable) ──────────────────────
        sep1 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep1.pack(fill=tk.X, padx=8, pady=(8, 4))

        size_header_frame = tk.Frame(panel)
        size_header_frame.pack(fill=tk.X, padx=8, pady=(4, 2))

        tk.Label(size_header_frame, text="Tile Size:", font=("", 10)).pack(side=tk.LEFT)

        self._custom_size_var = tk.BooleanVar(value=False)
        self._custom_size_check = tk.Checkbutton(
            size_header_frame, text="Custom", variable=self._custom_size_var,
            command=self._on_custom_size_toggled, font=("", 8)
        )
        self._custom_size_check.pack(side=tk.LEFT, padx=(8, 0))

        size_frame = tk.Frame(panel)
        size_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(size_frame, text="Width:", font=("", 8)).pack(side=tk.LEFT)
        self._tile_w_var = tk.IntVar(value=32)
        self._tile_w_spin = tk.Spinbox(size_frame, from_=1, to=9999, width=5,
                                       textvariable=self._tile_w_var, state=tk.DISABLED)
        self._tile_w_spin.pack(side=tk.LEFT, padx=4)

        tk.Label(size_frame, text="Height:", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))
        self._tile_h_var = tk.IntVar(value=32)
        self._tile_h_spin = tk.Spinbox(size_frame, from_=1, to=9999, width=5,
                                       textvariable=self._tile_h_var, state=tk.DISABLED)
        self._tile_h_spin.pack(side=tk.LEFT, padx=4)

        # ─── Output Grid Layout ─────────────────────────────────────────
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Output Grid:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        out_frame = tk.Frame(panel)
        out_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(out_frame, text="Rows:", font=("", 8)).pack(side=tk.LEFT)
        self._out_rows_var = tk.StringVar(value="")
        tk.Entry(out_frame, width=5, textvariable=self._out_rows_var).pack(
            side=tk.LEFT, padx=4)

        tk.Label(out_frame, text="Cols:", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))
        self._out_cols_var = tk.StringVar(value="")
        tk.Entry(out_frame, width=5, textvariable=self._out_cols_var).pack(
            side=tk.LEFT, padx=4)

        # Output info label
        self._out_info_var = tk.StringVar(value="")
        tk.Label(panel, textvariable=self._out_info_var, font=("", 8), fg="gray").pack(
            padx=8, anchor=tk.W
        )

        # Preview output checkbox
        self._preview_output_var = tk.BooleanVar(value=False)
        self._preview_output_check = tk.Checkbutton(
            panel, text="Preview output", variable=self._preview_output_var,
            command=self._on_preview_toggled, font=("", 9)
        )
        self._preview_output_check.pack(padx=8, pady=(4, 0), anchor=tk.W)

        # ─── Tile Info ──────────────────────────────────────────────────
        sep3 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep3.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._tile_info_var = tk.StringVar(value="Tiles: —")
        tk.Label(panel, textvariable=self._tile_info_var, font=("", 8), fg="gray").pack(
            padx=8, anchor=tk.W
        )

        # ─── Tile Selection & Flip ──────────────────────────────────────
        sep4 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep4.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Tile Flip:", font=("", 10)).pack(
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

        # Flip checkboxes
        flip_frame = tk.Frame(panel)
        flip_frame.pack(fill=tk.X, padx=8, pady=2)

        self._flip_h_var = tk.BooleanVar(value=False)
        self._flip_h_check = tk.Checkbutton(
            flip_frame, text="Flip Horizontal", variable=self._flip_h_var,
            command=self._on_flip_changed
        )
        self._flip_h_check.pack(side=tk.LEFT)

        self._flip_v_var = tk.BooleanVar(value=False)
        self._flip_v_check = tk.Checkbutton(
            flip_frame, text="Flip Vertical", variable=self._flip_v_var,
            command=self._on_flip_changed
        )
        self._flip_v_check.pack(side=tk.LEFT, padx=(8, 0))

        # ─── Tile Preview ───────────────────────────────────────────────
        sep5 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep5.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Tile Preview:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        # Preview canvas (fixed square)
        self._preview_size = 200
        self._preview_canvas = tk.Canvas(
            panel, width=self._preview_size, height=self._preview_size,
            bg="#3c3c3c", highlightthickness=0
        )
        self._preview_canvas.pack(padx=8, pady=4)

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
        """Set the source image. Resets state to defaults and guesses grid."""
        self._source_image = image
        self._flip_h_set.clear()
        self._flip_v_set.clear()
        self._tile_index_var.set(0)
        self._guess_grid_from_image()
        self._auto_compute_tile_size()
        self._on_params_changed()

    def reset(self):
        """Reset all state to defaults."""
        self._source_image = None
        self._custom_size_var.set(False)
        self._tile_w_spin.config(state=tk.DISABLED)
        self._tile_h_spin.config(state=tk.DISABLED)
        self._tile_w_var.set(32)
        self._tile_h_var.set(32)
        self._rows_var.set(1)
        self._cols_var.set(1)
        self._out_rows_var.set("")
        self._out_cols_var.set("")
        self._out_info_var.set("")
        self._preview_output_var.set(False)
        self._tile_index_var.set(0)
        self._flip_h_var.set(False)
        self._flip_v_var.set(False)
        self._flip_h_set.clear()
        self._flip_v_set.clear()
        self._tile_slider.config(to=0)
        self._tile_info_var.set("Tiles: —")
        self._preview_canvas.delete("all")
        self._preview_tk_image = None

    def get_grid_params(self):
        """Return current grid parameters as a dict."""
        try:
            tile_w = max(1, self._tile_w_var.get())
            tile_h = max(1, self._tile_h_var.get())
            rows = max(1, self._rows_var.get())
            cols = max(1, self._cols_var.get())
        except (tk.TclError, ValueError):
            return None

        return {
            "tile_w": tile_w,
            "tile_h": tile_h,
            "rows": rows,
            "cols": cols,
        }

    def get_output_dims(self):
        """Compute effective output rows and cols.

        Rules:
        - Both empty: use input rows/cols.
        - One filled: compute the other as ceil(tile_count / filled).
        - Both filled: use as-is.

        Returns (out_rows, out_cols) or None if invalid.
        """
        params = self.get_grid_params()
        if params is None:
            return None

        tile_count = params["rows"] * params["cols"]

        out_rows_str = self._out_rows_var.get().strip()
        out_cols_str = self._out_cols_var.get().strip()

        out_rows = None
        out_cols = None

        if out_rows_str:
            try:
                out_rows = max(1, int(out_rows_str))
            except ValueError:
                out_rows = None

        if out_cols_str:
            try:
                out_cols = max(1, int(out_cols_str))
            except ValueError:
                out_cols = None

        if out_rows is None and out_cols is None:
            # Both empty — use input dimensions
            out_rows = params["rows"]
            out_cols = params["cols"]
        elif out_rows is not None and out_cols is None:
            # Only rows filled — compute cols
            out_cols = math.ceil(tile_count / out_rows)
        elif out_cols is not None and out_rows is None:
            # Only cols filled — compute rows
            out_rows = math.ceil(tile_count / out_cols)
        # else: both filled, use as-is

        return (out_rows, out_cols)

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
            params["tile_w"], params["tile_h"],
            params["rows"], params["cols"],
        )

    # ─── Overlay Drawing ────────────────────────────────────────────────

    def draw_overlay(self, canvas, draw_x, draw_y, zoom_level):
        """Draw grid lines and flip indicators on the canvas."""
        if self._source_image is None:
            return

        params = self.get_grid_params()
        if params is None:
            return

        tile_w = params["tile_w"]
        tile_h = params["tile_h"]
        rows = params["rows"]
        cols = params["cols"]

        img_w, img_h = self._source_image.size
        if tile_w * cols > img_w or tile_h * rows > img_h:
            return

        # Helper to convert image coords to canvas coords
        def to_canvas(ix, iy):
            cx = draw_x + ix * zoom_level
            cy = draw_y + iy * zoom_level
            return cx, cy

        # Draw tile boundaries
        for row in range(rows):
            for col in range(cols):
                tx = col * tile_w
                ty = row * tile_h
                idx = row * cols + col

                tcx0, tcy0 = to_canvas(tx, ty)
                tcx1, tcy1 = to_canvas(tx + tile_w, ty + tile_h)
                canvas.create_rectangle(tcx0, tcy0, tcx1, tcy1,
                                        outline="#ffff00", width=1, dash=(2, 2))

                # Draw flip indicators
                center_cx = (tcx0 + tcx1) / 2
                center_cy = (tcy0 + tcy1) / 2
                indicator_size = min((tcx1 - tcx0), (tcy1 - tcy0)) * 0.2
                indicator_size = max(indicator_size, 4)

                if idx in self._flip_h_set:
                    # Horizontal flip indicator: horizontal double arrow
                    canvas.create_line(
                        center_cx - indicator_size, center_cy - indicator_size * 0.5,
                        center_cx + indicator_size, center_cy - indicator_size * 0.5,
                        fill="#00ffff", width=1, arrow=tk.BOTH
                    )

                if idx in self._flip_v_set:
                    # Vertical flip indicator: vertical double arrow
                    canvas.create_line(
                        center_cx + indicator_size * 0.5, center_cy - indicator_size,
                        center_cx + indicator_size * 0.5, center_cy + indicator_size,
                        fill="#ff00ff", width=1, arrow=tk.BOTH
                    )

                # Highlight selected tile
                try:
                    selected = self._tile_index_var.get()
                except tk.TclError:
                    selected = -1

                if idx == selected:
                    canvas.create_rectangle(tcx0 + 1, tcy0 + 1, tcx1 - 1, tcy1 - 1,
                                            outline="#00ff00", width=2)

    # ─── Internal ───────────────────────────────────────────────────────

    def _guess_grid_from_image(self):
        """Guess rows and cols assuming square tiles.

        Uses the GCD of image width and height as the tile size,
        giving the largest square tile that evenly divides both dimensions.
        """
        if self._source_image is None:
            return

        img_w, img_h = self._source_image.size
        if img_w <= 0 or img_h <= 0:
            return

        tile_size = math.gcd(img_w, img_h)
        cols = img_w // tile_size
        rows = img_h // tile_size

        self._suppress_params_changed = True
        self._cols_var.set(cols)
        self._rows_var.set(rows)
        self._suppress_params_changed = False

    def _auto_compute_tile_size(self):
        """Compute tile size from image dimensions and rows/cols."""
        if self._source_image is None:
            return
        if self._custom_size_var.get():
            return

        img_w, img_h = self._source_image.size
        try:
            rows = max(1, self._rows_var.get())
            cols = max(1, self._cols_var.get())
        except (tk.TclError, ValueError):
            return

        self._suppress_params_changed = True
        self._tile_w_var.set(img_w // cols)
        self._tile_h_var.set(img_h // rows)
        self._suppress_params_changed = False

    def _on_custom_size_toggled(self):
        """Handle the custom tile size checkbox toggle."""
        if self._custom_size_var.get():
            self._tile_w_spin.config(state=tk.NORMAL)
            self._tile_h_spin.config(state=tk.NORMAL)
        else:
            self._tile_w_spin.config(state=tk.DISABLED)
            self._tile_h_spin.config(state=tk.DISABLED)
            self._auto_compute_tile_size()
            self._on_params_changed()

    def _on_tile_size_changed(self):
        """Called when tile size spinboxes change (only matters in custom mode)."""
        if self._suppress_params_changed:
            return
        self._on_params_changed()

    def _on_params_changed(self):
        """Called when any parameter changes."""
        if self._suppress_params_changed:
            return

        # Auto-compute tile size when not in custom mode
        if not self._custom_size_var.get():
            self._auto_compute_tile_size()

        self._update_tile_info()
        self._update_output_info()
        self._update_slider_range()
        self._sync_flip_checkboxes()
        self._update_preview()
        self._notify_preview_changed()
        if self._on_overlay_changed:
            self._on_overlay_changed()

    def _on_flip_changed(self):
        """Called when a flip checkbox is toggled."""
        try:
            idx = self._tile_index_var.get()
        except tk.TclError:
            return

        if self._flip_h_var.get():
            self._flip_h_set.add(idx)
        else:
            self._flip_h_set.discard(idx)

        if self._flip_v_var.get():
            self._flip_v_set.add(idx)
        else:
            self._flip_v_set.discard(idx)

        self._update_preview()
        self._notify_preview_changed()
        if self._on_overlay_changed:
            self._on_overlay_changed()

    def _sync_flip_checkboxes(self):
        """Sync flip checkboxes to the currently selected tile."""
        try:
            idx = self._tile_index_var.get()
        except tk.TclError:
            idx = 0

        self._flip_h_var.set(idx in self._flip_h_set)
        self._flip_v_var.set(idx in self._flip_v_set)

    def _on_preview_toggled(self):
        """Handle the preview output checkbox toggle."""
        self._notify_preview_changed()

    def _notify_preview_changed(self):
        """Notify the parent about preview image change."""
        if not self._on_preview_changed:
            return

        if self._preview_output_var.get():
            output = self._compute_output_image()
            self._on_preview_changed(output)
        else:
            self._on_preview_changed(None)

    def _compute_output_image(self):
        """Compute the output image based on current settings.

        Returns the reassembled image or None if parameters are invalid.
        """
        if self._source_image is None:
            return None

        rects = self.get_tile_rects()
        if not rects:
            return None

        params = self.get_grid_params()
        if params is None:
            return None

        dims = self.get_output_dims()
        if dims is None:
            return None

        out_rows, out_cols = dims

        tiles = apply_tile_flips(
            self._source_image, rects, self._flip_h_set, self._flip_v_set
        )

        return reassemble_tiles(
            tiles,
            params["tile_w"], params["tile_h"],
            out_cols, out_rows,
            image_mode=self._source_image.mode,
        )

    def _update_tile_info(self):
        """Update the tile info label."""
        rects = self.get_tile_rects()
        if rects and len(rects) > 0:
            params = self.get_grid_params()
            self._tile_info_var.set(
                f"Tiles: {len(rects)} ({params['tile_w']}×{params['tile_h']} px)"
            )
        else:
            self._tile_info_var.set("Tiles: — (invalid grid)")

    def _update_output_info(self):
        """Update the output info label showing effective output dimensions."""
        dims = self.get_output_dims()
        if dims:
            out_rows, out_cols = dims
            self._out_info_var.set(f"→ Output: {out_rows} rows × {out_cols} cols")
        else:
            self._out_info_var.set("")

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
        """Update the tile preview canvas showing the selected tile with flips applied."""
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

        # Apply flips for preview
        if idx in self._flip_h_set:
            tile_img = tile_img.transpose(Image.FLIP_LEFT_RIGHT)
        if idx in self._flip_v_set:
            tile_img = tile_img.transpose(Image.FLIP_TOP_BOTTOM)

        # Fit tile into the fixed square preview area
        canvas_size = self._preview_size
        tile_w, tile_h = tile_img.size

        if tile_w <= 0 or tile_h <= 0:
            return

        scale_x = canvas_size / tile_w
        scale_y = canvas_size / tile_h
        scale = min(scale_x, scale_y)

        preview_w = max(1, int(tile_w * scale))
        preview_h = max(1, int(tile_h * scale))

        resample = Image.NEAREST if scale >= 1.0 else Image.LANCZOS
        preview_img = tile_img.resize((preview_w, preview_h), resample)

        # Handle RGBA — composite over dark background
        if preview_img.mode == "RGBA":
            bg = Image.new("RGB", (preview_w, preview_h), (60, 60, 60))
            bg.paste(preview_img, mask=preview_img.split()[3])
            preview_img = bg

        self._preview_tk_image = ImageTk.PhotoImage(preview_img)

        offset_x = (canvas_size - preview_w) // 2
        offset_y = (canvas_size - preview_h) // 2
        self._preview_canvas.create_image(
            offset_x, offset_y, anchor=tk.NW, image=self._preview_tk_image
        )

    # ─── Apply / Cancel ─────────────────────────────────────────────────

    def _apply(self):
        """Apply flips and reassemble tiles into the output image."""
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

        dims = self.get_output_dims()
        if dims is None:
            self._cancel()
            return

        out_rows, out_cols = dims

        tiles = apply_tile_flips(
            self._source_image, rects, self._flip_h_set, self._flip_v_set
        )

        result = reassemble_tiles(
            tiles,
            params["tile_w"], params["tile_h"],
            out_cols, out_rows,
            image_mode=self._source_image.mode,
        )

        if result is None:
            self._cancel()
            return

        self._on_apply(result)

    def _cancel(self):
        """Cancel and return to cursor tool."""
        self._on_cancel()
