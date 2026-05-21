"""Geometry correction side panel UI.

Similar to the Color Correction panel: uses a dual-viewer layout where
the user picks actual positions on the source image (left) and expected
positions on the reference image (right). The panel computes ax + b for
both axes and scales the source image accordingly.
"""

import tkinter as tk
from tkinter import ttk
import threading
import numpy as np
from PIL import Image

from geometry_correction import (
    compute_geometry_coefficients,
    apply_geometry_correction,
)
from scaling import RESAMPLE_METHODS


# Predefined background colors for empty areas
BG_COLORS = {
    "Transparent": (0, 0, 0, 0),
    "White": (255, 255, 255, 255),
    "Black": (0, 0, 0, 255),
    "Red": (255, 0, 0, 255),
    "Green": (0, 255, 0, 255),
    "Blue": (0, 0, 255, 255),
    "Magenta": (255, 0, 255, 255),
    "Gray": (128, 128, 128, 255),
    "Average": None,  # computed from image
}


class GeometryCorrectionPanel:
    """Side panel for the geometry correction tool.

    Manages a list of point pairs (actual pixel position on source vs.
    expected position on reference) and provides preview/apply/cancel
    controls. Computes linear regression (ax + b) for both X and Y axes
    and applies scaling.
    """

    DEBOUNCE_MS = 300

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
        self.points = []  # list of dicts: src_x, src_y, ref_x, ref_y, src_color, ref_color
        self._source_image = None
        self._reference_image = None
        self._preview_result = None
        self._bg_color_override = None  # set by right-click

        # Which side is being picked: None, "src", or "ref"
        self._picking = None
        # Temp storage for pending source point
        self._pending_src = None

        # Threading
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._debounce_id = None

        self._build_ui()

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Geometry Correction", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # Instructions
        tk.Label(
            panel,
            text="Click source (left) for actual position,\nthen reference (right) for expected.",
            font=("", 8), justify=tk.LEFT
        ).pack(padx=8, anchor=tk.W)

        # Status of current pick
        self._pick_status_var = tk.StringVar(value="")
        self._pick_status_label = tk.Label(
            panel, textvariable=self._pick_status_var, font=("", 9, "italic"), fg="blue"
        )
        self._pick_status_label.pack(padx=8, anchor=tk.W, pady=(4, 2))

        # ─── Offset Mode ────────────────────────────────────────────────
        sep_mode = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_mode.pack(fill=tk.X, padx=8, pady=(8, 4))

        offset_frame = tk.Frame(panel)
        offset_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(offset_frame, text="Offset Mode:").pack(side=tk.LEFT)
        self._offset_mode_var = tk.StringVar(value="Ignore")
        self._offset_dropdown = ttk.Combobox(
            offset_frame, textvariable=self._offset_mode_var,
            values=["Ignore", "Shrink", "Expand", "Keep"],
            state="readonly", width=8
        )
        self._offset_dropdown.pack(side=tk.LEFT, padx=4)
        self._offset_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_settings_changed())

        # ─── Resampling Method ──────────────────────────────────────────
        resample_frame = tk.Frame(panel)
        resample_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(resample_frame, text="Resample:").pack(side=tk.LEFT)
        self._resample_var = tk.StringVar(value="Lanczos")
        ttk.Combobox(
            resample_frame, textvariable=self._resample_var,
            values=list(RESAMPLE_METHODS.keys()), state="readonly", width=10
        ).pack(side=tk.LEFT, padx=4)
        self._resample_var.trace_add("write", lambda *_: self._on_settings_changed())

        # ─── Background Color ───────────────────────────────────────────
        sep_bg = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_bg.pack(fill=tk.X, padx=8, pady=(8, 4))

        bg_frame = tk.Frame(panel)
        bg_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(bg_frame, text="Background:").pack(side=tk.LEFT)
        self._bg_color_var = tk.StringVar(value="Transparent")
        self._bg_dropdown = ttk.Combobox(
            bg_frame, textvariable=self._bg_color_var,
            values=list(BG_COLORS.keys()), state="readonly", width=12
        )
        self._bg_dropdown.pack(side=tk.LEFT, padx=4)
        self._bg_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_settings_changed())

        # Background color swatch (shows current bg color; right-click to pick from image)
        self._bg_swatch = tk.Canvas(bg_frame, width=20, height=14,
                                    highlightthickness=1, highlightbackground="black")
        self._bg_swatch.pack(side=tk.LEFT, padx=4)
        self._update_bg_swatch()

        tk.Label(panel, text="(Right-click image to pick bg color)", font=("", 7), fg="gray").pack(
            padx=8, anchor=tk.W
        )

        # ─── Preview Background (for viewer) ────────────────────────────
        sep_preview_bg = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_preview_bg.pack(fill=tk.X, padx=8, pady=(8, 4))

        preview_bg_frame = tk.Frame(panel)
        preview_bg_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(preview_bg_frame, text="Preview BG:").pack(side=tk.LEFT)
        self._preview_bg_var = tk.StringVar(value="None")
        self._preview_bg_dropdown = ttk.Combobox(
            preview_bg_frame, textvariable=self._preview_bg_var,
            values=["None", "White", "Black", "Red", "Green", "Blue", "Magenta", "Gray"],
            state="readonly", width=10
        )
        self._preview_bg_dropdown.pack(side=tk.LEFT, padx=4)
        self._preview_bg_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_preview_bg_changed())

        # ─── Coefficients Display ───────────────────────────────────────
        sep_coeff = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_coeff.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._coeff_var = tk.StringVar(value="Coefficients: (need ≥2 points)")
        tk.Label(panel, textvariable=self._coeff_var, font=("", 8), fg="gray").pack(
            padx=8, anchor=tk.W
        )

        # ─── Points List ────────────────────────────────────────────────
        sep_pts = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_pts.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Point Pairs:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        list_frame = tk.Frame(panel)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._points_canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                 command=self._points_canvas.yview)
        self._points_inner_frame = tk.Frame(self._points_canvas)

        self._points_inner_frame.bind(
            "<Configure>",
            lambda e: self._points_canvas.configure(
                scrollregion=self._points_canvas.bbox("all")
            )
        )
        self._points_canvas.create_window((0, 0), window=self._points_inner_frame, anchor=tk.NW)
        self._points_canvas.configure(yscrollcommand=scrollbar.set)

        self._points_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ─── Preview Checkbox ───────────────────────────────────────────
        sep_prev = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_prev.pack(fill=tk.X, padx=8, pady=(8, 4))

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
        self.points = []
        self._picking = None
        self._pending_src = None
        self._preview_result = None
        self._preview_var.set(False)
        self._bg_color_override = None
        self._pick_status_var.set("")
        self._coeff_var.set("Coefficients: (need ≥2 points)")
        self._refresh_points_list()
        self._update_status("")
        self._update_bg_swatch()

    def on_source_click(self, img_x, img_y):
        """Handle a click on the source (left) image — marks actual position."""
        if self._source_image is None:
            return

        if self._picking == "ref":
            # Was waiting for reference but user clicked source again — restart
            pass

        color = self._get_pixel_color(self._source_image, img_x, img_y)
        if color is None:
            return
        self._pending_src = {"x": img_x, "y": img_y, "color": color}
        self._picking = "ref"
        self._pick_status_var.set(
            f"Actual: ({img_x}, {img_y}) — now click reference image"
        )

    def on_reference_click(self, img_x, img_y):
        """Handle a click on the reference (right) image — marks expected position."""
        if self._reference_image is None:
            return

        if self._picking == "ref" and self._pending_src is not None:
            # Completing a pair: expected position picked after actual
            color = self._get_pixel_color(self._reference_image, img_x, img_y)
            if color is None:
                return
            point = {
                "src_x": self._pending_src["x"],
                "src_y": self._pending_src["y"],
                "src_color": self._pending_src["color"],
                "ref_x": img_x,
                "ref_y": img_y,
                "ref_color": color,
                # For geometry correction, map to img_x/exp_x format
                "img_x": self._pending_src["x"],
                "img_y": self._pending_src["y"],
                "exp_x": img_x,
                "exp_y": img_y,
            }
            self.points.append(point)
            self._pending_src = None
            self._picking = None
            self._pick_status_var.set("")
            self._refresh_points_list()
            self._update_coefficients()
            self._schedule_preview()
        elif self._picking is None:
            # Start a new pair from reference side: expected picked first
            color = self._get_pixel_color(self._reference_image, img_x, img_y)
            if color is None:
                return
            self._pending_ref = {"x": img_x, "y": img_y, "color": color}
            self._picking = "src"
            self._pick_status_var.set(
                f"Expected: ({img_x}, {img_y}) — now click source image"
            )
        elif self._picking == "src":
            # Was waiting for source but user clicked reference again — cancel
            self._picking = None
            self._pending_ref = None
            self._pick_status_var.set("")

    def on_source_click_after_ref(self, img_x, img_y):
        """Handle source click when reference was picked first."""
        if self._picking == "src" and hasattr(self, '_pending_ref') and self._pending_ref is not None:
            color = self._get_pixel_color(self._source_image, img_x, img_y)
            if color is None:
                return
            point = {
                "src_x": img_x,
                "src_y": img_y,
                "src_color": color,
                "ref_x": self._pending_ref["x"],
                "ref_y": self._pending_ref["y"],
                "ref_color": self._pending_ref["color"],
                "img_x": img_x,
                "img_y": img_y,
                "exp_x": self._pending_ref["x"],
                "exp_y": self._pending_ref["y"],
            }
            self.points.append(point)
            self._pending_ref = None
            self._picking = None
            self._pick_status_var.set("")
            self._refresh_points_list()
            self._update_coefficients()
            self._schedule_preview()
            return True
        return False

    def on_right_click(self, img_x, img_y):
        """Handle a right-click on either image to pick background color."""
        if self._source_image is None:
            return
        color = self._get_pixel_color(self._source_image, img_x, img_y)
        if color is not None:
            self._bg_color_override = (color[0], color[1], color[2], 255)
            self._bg_color_var.set("Transparent")  # reset dropdown since we have custom
            self._update_bg_swatch()
            self._on_settings_changed()

    def get_preview_bg_color(self):
        """Return the preview background color for the viewer, or None for checkerboard."""
        name = self._preview_bg_var.get()
        if name == "None":
            return None
        preview_colors = {
            "White": (255, 255, 255),
            "Black": (0, 0, 0),
            "Red": (255, 0, 0),
            "Green": (0, 255, 0),
            "Blue": (0, 0, 255),
            "Magenta": (255, 0, 255),
            "Gray": (128, 128, 128),
        }
        return preview_colors.get(name, None)

    # ─── Points List UI ─────────────────────────────────────────────────

    def _refresh_points_list(self):
        for widget in self._points_inner_frame.winfo_children():
            widget.destroy()

        for i, pt in enumerate(self.points):
            frame = tk.Frame(self._points_inner_frame, bd=1, relief=tk.GROOVE)
            frame.pack(fill=tk.X, pady=2)

            # Header row
            header = tk.Frame(frame)
            header.pack(fill=tk.X, padx=4, pady=2)

            tk.Label(header, text=f"Pair #{i + 1}", font=("", 9, "bold")).pack(side=tk.LEFT)
            tk.Button(
                header, text="✕", font=("", 8), bd=0,
                command=lambda idx=i: self._remove_point(idx)
            ).pack(side=tk.RIGHT)

            # Source row with color swatch
            src_row = tk.Frame(frame)
            src_row.pack(fill=tk.X, padx=4, pady=1)

            src_color = pt.get("src_color", (128, 128, 128))
            src_hex = f"#{src_color[0]:02x}{src_color[1]:02x}{src_color[2]:02x}"
            src_swatch = tk.Canvas(src_row, width=14, height=14, highlightthickness=1,
                                   highlightbackground="black")
            src_swatch.pack(side=tk.LEFT, padx=(0, 4))
            src_swatch.create_rectangle(0, 0, 14, 14, fill=src_hex, outline="")

            tk.Label(
                src_row,
                text=f"Actual: ({pt['src_x']}, {pt['src_y']})",
                font=("", 8)
            ).pack(side=tk.LEFT)

            # Reference row with color swatch
            ref_row = tk.Frame(frame)
            ref_row.pack(fill=tk.X, padx=4, pady=1)

            ref_color = pt.get("ref_color", (128, 128, 128))
            ref_hex = f"#{ref_color[0]:02x}{ref_color[1]:02x}{ref_color[2]:02x}"
            ref_swatch = tk.Canvas(ref_row, width=14, height=14, highlightthickness=1,
                                   highlightbackground="black")
            ref_swatch.pack(side=tk.LEFT, padx=(0, 4))
            ref_swatch.create_rectangle(0, 0, 14, 14, fill=ref_hex, outline="")

            tk.Label(
                ref_row,
                text=f"Expected: ({pt['ref_x']}, {pt['ref_y']})",
                font=("", 8)
            ).pack(side=tk.LEFT)

            # Difference display
            diff_x = pt["exp_x"] - pt["img_x"]
            diff_y = pt["exp_y"] - pt["img_y"]
            diff_frame = tk.Frame(frame)
            diff_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
            tk.Label(
                diff_frame,
                text=f"Δx: {diff_x:+d}  Δy: {diff_y:+d}",
                font=("", 8), fg="#666666"
            ).pack(side=tk.LEFT)

    def _remove_point(self, idx):
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            self._refresh_points_list()
            self._update_coefficients()
            self._schedule_preview()

    # ─── Coefficients ───────────────────────────────────────────────────

    def _update_coefficients(self):
        """Update the coefficients display."""
        if len(self.points) < 2:
            self._coeff_var.set("Coefficients: (need ≥2 points)")
            return

        coeffs = compute_geometry_coefficients(self.points)
        if coeffs is None:
            self._coeff_var.set("Coefficients: error computing")
            return

        self._coeff_var.set(
            f"X: {coeffs['a_x']:.4f}x + {coeffs['b_x']:.1f}  |  "
            f"Y: {coeffs['a_y']:.4f}y + {coeffs['b_y']:.1f}"
        )

    # ─── Settings Changed ───────────────────────────────────────────────

    def _on_settings_changed(self):
        """Called when offset mode, resample, or bg color changes."""
        self._update_bg_swatch()
        self._schedule_preview()

    def _on_preview_bg_changed(self):
        """Called when preview background dropdown changes."""
        # Re-render the viewer with new bg
        if self._preview_result is not None:
            self._on_preview_ready(self._preview_result)

    # ─── Background Color ───────────────────────────────────────────────

    def _get_effective_bg_color(self):
        """Get the effective background color for the correction."""
        if self._bg_color_override is not None:
            return self._bg_color_override

        name = self._bg_color_var.get()
        if name == "Average" and self._source_image is not None:
            return self._compute_average_color()

        color = BG_COLORS.get(name, (0, 0, 0, 0))
        if color is None:
            return self._compute_average_color()
        return color

    def _compute_average_color(self):
        """Compute the average color of the source image."""
        if self._source_image is None:
            return (128, 128, 128, 255)
        arr = np.array(self._source_image.convert("RGB"))
        avg = arr.mean(axis=(0, 1)).round().astype(int)
        return (int(avg[0]), int(avg[1]), int(avg[2]), 255)

    def _update_bg_swatch(self):
        """Update the background color swatch display."""
        color = self._get_effective_bg_color()
        if color[3] == 0:
            # Transparent — show checkerboard pattern
            self._bg_swatch.delete("all")
            self._bg_swatch.create_rectangle(0, 0, 10, 7, fill="#cccccc", outline="")
            self._bg_swatch.create_rectangle(10, 0, 20, 7, fill="#ffffff", outline="")
            self._bg_swatch.create_rectangle(0, 7, 10, 14, fill="#ffffff", outline="")
            self._bg_swatch.create_rectangle(10, 7, 20, 14, fill="#cccccc", outline="")
        else:
            hex_color = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            self._bg_swatch.delete("all")
            self._bg_swatch.create_rectangle(0, 0, 20, 14, fill=hex_color, outline="")

    # ─── Preview ────────────────────────────────────────────────────────

    def _on_preview_toggled(self):
        if self._preview_var.get():
            self._schedule_preview()
        else:
            self._preview_result = None
            self._on_preview_ready(None)

    def _schedule_preview(self):
        if self._debounce_id is not None:
            self.parent_frame.after_cancel(self._debounce_id)
            self._debounce_id = None

        self._cancel_processing()

        if not self._preview_var.get():
            return

        if len(self.points) < 2 or self._source_image is None:
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
        points_snapshot = [p.copy() for p in self.points]
        cancel_event = self._cancel_event
        offset_mode = self._offset_mode_var.get().lower()
        resample_method = self._resample_var.get()
        bg_color = self._get_effective_bg_color()

        self._update_status("Processing...")

        def worker():
            result = apply_geometry_correction(
                source_image, points_snapshot,
                offset_mode=offset_mode,
                resample_method=resample_method,
                bg_color=bg_color,
                cancel_event=cancel_event
            )
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
        """Apply the geometry correction."""
        self._cancel_processing()
        if self._preview_result is not None:
            self._on_apply(self._preview_result)
        elif len(self.points) >= 2 and self._source_image is not None:
            # Compute synchronously
            self._update_status("Applying...")
            offset_mode = self._offset_mode_var.get().lower()
            resample_method = self._resample_var.get()
            bg_color = self._get_effective_bg_color()
            result = apply_geometry_correction(
                self._source_image, self.points,
                offset_mode=offset_mode,
                resample_method=resample_method,
                bg_color=bg_color,
            )
            if result is not None:
                self._on_apply(result)
        self._preview_result = None

    def _cancel(self):
        self._cancel_processing()
        self._preview_result = None
        self._on_cancel()

    def _clear_all(self):
        self._cancel_processing()
        self.points = []
        self._pending_src = None
        self._picking = None
        self._preview_result = None
        self._bg_color_override = None
        self._pick_status_var.set("")
        self._coeff_var.set("Coefficients: (need ≥2 points)")
        self._refresh_points_list()
        self._update_status("")
        self._update_bg_swatch()
        self._on_preview_ready(None)

    # ─── Helpers ────────────────────────────────────────────────────────

    def _get_pixel_color(self, image, x, y):
        """Get the RGB color at (x, y) from the given image."""
        if image is None:
            return None
        rgb = image.convert("RGB")
        w, h = rgb.size
        if x < 0 or x >= w or y < 0 or y >= h:
            return None
        arr = np.array(rgb)
        return tuple(arr[y, x])

    def _update_status(self, text):
        self._status_label.config(text=text)
        if self._on_status_changed:
            status = text if text else "Ready"
            self._on_status_changed(status)
