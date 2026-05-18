"""Color correction side panel UI."""

import tkinter as tk
from tkinter import ttk
import threading
import math
import numpy as np
from PIL import Image

from color_correction import apply_color_correction


class ColorCorrectionPanel:
    """Side panel for the color correction tool.

    Manages a list of color pairs (source pixel, reference pixel) and
    provides preview/apply/cancel controls.
    """

    DEBOUNCE_MS = 400

    def __init__(self, parent_frame, on_preview_ready, on_apply, on_cancel,
                 on_status_changed=None):
        """Initialize the panel.

        Args:
            parent_frame: Parent tk.Frame to build UI into.
            on_preview_ready: Callback(image) when preview is computed.
            on_apply: Callback(image) when user applies correction.
            on_cancel: Callback() when user cancels.
            on_status_changed: Callback(text) for status updates.
        """
        self.parent_frame = parent_frame
        self._on_preview_ready = on_preview_ready
        self._on_apply = on_apply
        self._on_cancel = on_cancel
        self._on_status_changed = on_status_changed

        # State
        self.pairs = []  # list of dicts: src_x, src_y, ref_x, ref_y, src_color, ref_color
        self._source_image = None
        self._reference_image = None
        self._preview_result = None

        # Which side is being picked: None, "src", or "ref"
        self._picking = None
        # Index of pair being edited (None = adding new pair)
        self._editing_index = None

        # Threading
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._debounce_id = None

        self._build_ui()

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Color Correction", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # Instructions
        tk.Label(
            panel,
            text="Click source (left) then reference (right)\nto add color pairs.",
            font=("", 8), justify=tk.LEFT
        ).pack(padx=8, anchor=tk.W)

        # Status of current pick
        self._pick_status_var = tk.StringVar(value="")
        self._pick_status_label = tk.Label(
            panel, textvariable=self._pick_status_var, font=("", 9, "italic"), fg="blue"
        )
        self._pick_status_label.pack(padx=8, anchor=tk.W, pady=(4, 2))

        # ─── Area Averaging ─────────────────────────────────────────────
        sep_avg = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_avg.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._use_area_avg_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Average color over area",
            variable=self._use_area_avg_var,
        ).pack(padx=8, anchor=tk.W)

        avg_opts_frame = tk.Frame(panel)
        avg_opts_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(avg_opts_frame, text="Size (n):", font=("", 8)).pack(side=tk.LEFT)
        self._area_size_var = tk.IntVar(value=2)
        tk.Spinbox(
            avg_opts_frame, from_=1, to=50, width=4,
            textvariable=self._area_size_var
        ).pack(side=tk.LEFT, padx=4)

        tk.Label(avg_opts_frame, text="Shape:", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))
        self._area_shape_var = tk.StringVar(value="Square")
        ttk.Combobox(
            avg_opts_frame, textvariable=self._area_shape_var,
            values=["Square", "Round"], state="readonly", width=7
        ).pack(side=tk.LEFT, padx=4)

        # ─── Pairs List ─────────────────────────────────────────────────
        sep = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Color Pairs:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        list_frame = tk.Frame(panel)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._pairs_canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                 command=self._pairs_canvas.yview)
        self._pairs_inner_frame = tk.Frame(self._pairs_canvas)

        self._pairs_inner_frame.bind(
            "<Configure>",
            lambda e: self._pairs_canvas.configure(
                scrollregion=self._pairs_canvas.bbox("all")
            )
        )
        self._pairs_canvas.create_window((0, 0), window=self._pairs_inner_frame, anchor=tk.NW)
        self._pairs_canvas.configure(yscrollcommand=scrollbar.set)

        self._pairs_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ─── Preview Checkbox ───────────────────────────────────────────
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._preview_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Preview correction",
            variable=self._preview_var,
            command=self._on_preview_toggled
        ).pack(padx=8, anchor=tk.W)

        # Status label
        self._status_label = tk.Label(panel, text="", font=("", 8), fg="gray")
        self._status_label.pack(padx=8, anchor=tk.W, pady=(4, 0))

        # ─── Bottom Buttons ─────────────────────────────────────────────
        btn_frame = tk.Frame(panel)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)

        tk.Button(btn_frame, text="Clear All", command=self._clear_all).pack(
            side=tk.LEFT, padx=2
        )
        tk.Button(btn_frame, text="Apply", command=self._apply).pack(
            side=tk.RIGHT, padx=2
        )
        tk.Button(btn_frame, text="Cancel", command=self._cancel).pack(
            side=tk.RIGHT, padx=2
        )

    # ─── Public Interface ───────────────────────────────────────────────

    def set_source_image(self, image):
        """Set the source image (left viewer)."""
        self._source_image = image

    def set_reference_image(self, image):
        """Set the reference image (right viewer)."""
        self._reference_image = image

    def reset(self):
        """Reset all state."""
        self._cancel_processing()
        self.pairs = []
        self._picking = None
        self._editing_index = None
        self._preview_result = None
        self._preview_var.set(False)
        self._pick_status_var.set("")
        self._refresh_pairs_list()
        self._update_status("")

    def on_source_click(self, img_x, img_y):
        """Handle a click on the source (left) image."""
        if self._source_image is None:
            return

        if self._editing_index is not None:
            # Editing an existing pair's source point
            idx = self._editing_index
            color = self._get_pixel_color(self._source_image, img_x, img_y)
            if color is None:
                return
            self.pairs[idx]["src_x"] = img_x
            self.pairs[idx]["src_y"] = img_y
            self.pairs[idx]["src_color"] = color
            self._editing_index = None
            self._picking = None
            self._pick_status_var.set("")
            self._refresh_pairs_list()
            self._schedule_preview()
            return

        if self._picking == "ref":
            # Was waiting for reference but user clicked source again — cancel pick
            self._picking = None
            self._pick_status_var.set("")
        elif self._picking is None:
            # Start a new pair: source picked first
            color = self._get_pixel_color(self._source_image, img_x, img_y)
            if color is None:
                return
            self._pending_src = {"x": img_x, "y": img_y, "color": color}
            self._picking = "ref"
            self._pick_status_var.set(
                f"Source: ({img_x}, {img_y}) — now click reference image"
            )
        elif self._picking == "src":
            # Was waiting for source (after ref was picked first) — complete pair
            color = self._get_pixel_color(self._source_image, img_x, img_y)
            if color is None:
                return
            pair = {
                "src_x": img_x, "src_y": img_y, "src_color": color,
                "ref_x": self._pending_ref["x"],
                "ref_y": self._pending_ref["y"],
                "ref_color": self._pending_ref["color"],
            }
            self.pairs.append(pair)
            self._picking = None
            self._pick_status_var.set("")
            self._refresh_pairs_list()
            self._schedule_preview()

    def on_reference_click(self, img_x, img_y):
        """Handle a click on the reference (right) image."""
        if self._reference_image is None:
            return

        if self._editing_index is not None:
            # Editing an existing pair's reference point
            idx = self._editing_index
            color = self._get_pixel_color(self._reference_image, img_x, img_y)
            if color is None:
                return
            self.pairs[idx]["ref_x"] = img_x
            self.pairs[idx]["ref_y"] = img_y
            self.pairs[idx]["ref_color"] = color
            self._editing_index = None
            self._picking = None
            self._pick_status_var.set("")
            self._refresh_pairs_list()
            self._schedule_preview()
            return

        if self._picking == "ref":
            # Completing a pair: reference picked after source
            color = self._get_pixel_color(self._reference_image, img_x, img_y)
            if color is None:
                return
            pair = {
                "src_x": self._pending_src["x"],
                "src_y": self._pending_src["y"],
                "src_color": self._pending_src["color"],
                "ref_x": img_x, "ref_y": img_y, "ref_color": color,
            }
            self.pairs.append(pair)
            self._picking = None
            self._pick_status_var.set("")
            self._refresh_pairs_list()
            self._schedule_preview()
        elif self._picking == "src":
            # Was waiting for source but user clicked reference again — cancel pick
            self._picking = None
            self._pick_status_var.set("")
        elif self._picking is None:
            # Start a new pair: reference picked first
            color = self._get_pixel_color(self._reference_image, img_x, img_y)
            if color is None:
                return
            self._pending_ref = {"x": img_x, "y": img_y, "color": color}
            self._picking = "src"
            self._pick_status_var.set(
                f"Reference: ({img_x}, {img_y}) — now click source image"
            )

    # ─── Pairs List UI ──────────────────────────────────────────────────

    def _refresh_pairs_list(self):
        for widget in self._pairs_inner_frame.winfo_children():
            widget.destroy()

        for i, pair in enumerate(self.pairs):
            frame = tk.Frame(self._pairs_inner_frame, bd=1, relief=tk.GROOVE)
            frame.pack(fill=tk.X, pady=2)

            # Header row
            header = tk.Frame(frame)
            header.pack(fill=tk.X, padx=4, pady=2)

            tk.Label(header, text=f"Pair #{i + 1}", font=("", 9, "bold")).pack(side=tk.LEFT)
            tk.Button(
                header, text="✕", font=("", 8), bd=0,
                command=lambda idx=i: self._remove_pair(idx)
            ).pack(side=tk.RIGHT)

            # Source row
            src_row = tk.Frame(frame)
            src_row.pack(fill=tk.X, padx=4, pady=1)

            src_color = pair["src_color"]
            src_hex = f"#{src_color[0]:02x}{src_color[1]:02x}{src_color[2]:02x}"
            src_swatch = tk.Canvas(src_row, width=14, height=14, highlightthickness=1,
                                   highlightbackground="black")
            src_swatch.pack(side=tk.LEFT, padx=(0, 4))
            src_swatch.create_rectangle(0, 0, 14, 14, fill=src_hex, outline="")

            tk.Label(
                src_row,
                text=f"Src: ({pair['src_x']}, {pair['src_y']})",
                font=("", 8)
            ).pack(side=tk.LEFT)

            tk.Button(
                src_row, text="Edit", font=("", 7), bd=1,
                command=lambda idx=i: self._edit_source(idx)
            ).pack(side=tk.RIGHT, padx=2)

            # Reference row
            ref_row = tk.Frame(frame)
            ref_row.pack(fill=tk.X, padx=4, pady=1)

            ref_color = pair["ref_color"]
            ref_hex = f"#{ref_color[0]:02x}{ref_color[1]:02x}{ref_color[2]:02x}"
            ref_swatch = tk.Canvas(ref_row, width=14, height=14, highlightthickness=1,
                                   highlightbackground="black")
            ref_swatch.pack(side=tk.LEFT, padx=(0, 4))
            ref_swatch.create_rectangle(0, 0, 14, 14, fill=ref_hex, outline="")

            tk.Label(
                ref_row,
                text=f"Ref: ({pair['ref_x']}, {pair['ref_y']})",
                font=("", 8)
            ).pack(side=tk.LEFT)

            tk.Button(
                ref_row, text="Edit", font=("", 7), bd=1,
                command=lambda idx=i: self._edit_reference(idx)
            ).pack(side=tk.RIGHT, padx=2)

            # Color distance row
            dist = math.sqrt(sum(
                (s - r) ** 2 for s, r in zip(src_color, ref_color)
            ))
            # Normalize to 0-255 range (max RGB distance is sqrt(3*255^2) ≈ 441.67)
            dist_normalized = min(255, int(dist * 255 / 441.67))
            tk.Label(
                frame,
                text=f"Distance: {dist_normalized}",
                font=("", 8), fg="#666666"
            ).pack(padx=4, anchor=tk.W, pady=(0, 2))

    def _remove_pair(self, idx):
        if 0 <= idx < len(self.pairs):
            self.pairs.pop(idx)
            self._refresh_pairs_list()
            self._schedule_preview()

    def _edit_source(self, idx):
        """Enter edit mode for the source point of pair at idx."""
        self._editing_index = idx
        self._picking = "edit_src"
        self._pick_status_var.set(f"Click source image to update pair #{idx + 1} source")

    def _edit_reference(self, idx):
        """Enter edit mode for the reference point of pair at idx."""
        self._editing_index = idx
        self._picking = "edit_ref"
        self._pick_status_var.set(f"Click reference image to update pair #{idx + 1} reference")

    # ─── Preview ────────────────────────────────────────────────────────

    def _on_preview_toggled(self):
        if self._preview_var.get():
            self._schedule_preview()
        else:
            # Show original
            self._on_preview_ready(None)

    def _schedule_preview(self):
        if self._debounce_id is not None:
            self.parent_frame.after_cancel(self._debounce_id)
            self._debounce_id = None

        self._cancel_processing()

        if not self._preview_var.get():
            return

        if not self.pairs or self._source_image is None:
            self._preview_result = None
            self._on_preview_ready(None)
            self._update_status("")
            return

        self._update_status("Waiting...")
        self._debounce_id = self.parent_frame.after(self.DEBOUNCE_MS, self._start_processing)

    def _cancel_processing(self):
        self._cancel_event.set()

    def _start_processing(self):
        self._debounce_id = None
        self._cancel_event = threading.Event()

        source_image = self._source_image.copy()
        pairs_snapshot = [p.copy() for p in self.pairs]
        cancel_event = self._cancel_event

        self._update_status("Processing...")

        def worker():
            result = apply_color_correction(source_image, pairs_snapshot, cancel_event)
            if not cancel_event.is_set() and result is not None:
                self.parent_frame.after(0, lambda: self._on_worker_done(result))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_worker_done(self, result):
        self._preview_result = result
        self._update_status("Preview ready")
        self._on_preview_ready(result)

    # ─── Apply / Cancel ─────────────────────────────────────────────────

    def _apply(self):
        """Apply the correction. If no preview computed yet, compute synchronously."""
        self._cancel_processing()
        if self._preview_result is not None:
            self._on_apply(self._preview_result)
        elif self.pairs and self._source_image is not None:
            # Compute now
            self._update_status("Applying...")
            result = apply_color_correction(self._source_image, self.pairs)
            if result is not None:
                self._on_apply(result)
        self._preview_result = None

    def _cancel(self):
        self._cancel_processing()
        self._preview_result = None
        self._on_cancel()

    def _clear_all(self):
        self._cancel_processing()
        self.pairs = []
        self._picking = None
        self._editing_index = None
        self._preview_result = None
        self._pick_status_var.set("")
        self._refresh_pairs_list()
        self._update_status("")
        self._on_preview_ready(None)

    # ─── Helpers ────────────────────────────────────────────────────────

    def _get_pixel_color(self, image, x, y):
        """Get the RGB color at (x, y), optionally averaged over a kernel area."""
        w, h = image.size
        if x < 0 or x >= w or y < 0 or y >= h:
            return None

        rgb = image.convert("RGB")
        arr = np.array(rgb)

        if not self._use_area_avg_var.get():
            return tuple(arr[y, x])

        # Area averaging with kernel size = 2*n + 1
        try:
            n = self._area_size_var.get()
        except tk.TclError:
            n = 2
        radius = n  # half-size; full kernel is (2*n+1) x (2*n+1)
        shape = self._area_shape_var.get()

        # Compute bounding box
        x0 = max(0, x - radius)
        y0 = max(0, y - radius)
        x1 = min(w, x + radius + 1)
        y1 = min(h, y + radius + 1)

        region = arr[y0:y1, x0:x1]  # (ky, kx, 3)

        if shape == "Round":
            # Build a circular mask
            ky, kx = region.shape[:2]
            cy, cx = (y - y0), (x - x0)
            yy, xx = np.ogrid[:ky, :kx]
            dist_sq = (xx - cx) ** 2 + (yy - cy) ** 2
            mask = dist_sq <= radius * radius
            if not np.any(mask):
                return tuple(arr[y, x])
            pixels = region[mask]  # (M, 3)
        else:
            # Square — use entire region
            pixels = region.reshape(-1, 3)

        avg = pixels.mean(axis=0).round().astype(np.uint8)
        return tuple(avg)

    def _update_status(self, text):
        self._status_label.config(text=text)
        if self._on_status_changed:
            status = text if text else "Ready"
            self._on_status_changed(status)
