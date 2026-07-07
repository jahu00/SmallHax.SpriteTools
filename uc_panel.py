"""Uniform color side panel UI with debounced threaded preview."""

import tkinter as tk
from tkinter import ttk
import threading
import copy

from uniform_color import process_uniform_color
from panel_utils import ReflowingList


class UniformColorPanel:
    """Side panel for the uniform color tool.

    Similar to BgRemovalPanel but replaces masked pixels with their
    averaged color instead of making them transparent. Border pixels
    get a smooth blend.
    """

    DEBOUNCE_MS = 300

    def __init__(self, parent_frame, on_preview_ready, on_apply, on_cancel,
                 on_status_changed=None):
        self.parent_frame = parent_frame
        self._on_preview_ready = on_preview_ready
        self._on_apply = on_apply
        self._on_cancel = on_cancel
        self._on_status_changed = on_status_changed

        # State
        self.points = []
        self._source_image = None
        self._preview_result = None
        self._point_colors = []  # RGB tuples for color swatches

        # Threading
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._debounce_id = None

        self._build_ui()
        # Register traces after UI is fully built
        self.blend_thresh_var.trace_add("write", lambda *_: self._schedule_preview())
        self.global_thresh_var.trace_add("write", lambda *_: self._on_global_thresh_changed())
        self.global_feather_var.trace_add("write", lambda *_: self._on_global_feather_changed())

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Uniform Color", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # ─── Distance Metric ────────────────────────────────────────────
        dm_frame = tk.Frame(panel)
        dm_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(dm_frame, text="Distance Metric:").pack(side=tk.LEFT)
        self.distance_metric_var = tk.StringVar(value="RGB")
        self.distance_metric_dropdown = ttk.Combobox(
            dm_frame, textvariable=self.distance_metric_var,
            values=["RGB", "LAB"], state="readonly", width=5
        )
        self.distance_metric_dropdown.pack(side=tk.LEFT, padx=4)
        self.distance_metric_dropdown.bind(
            "<<ComboboxSelected>>", lambda e: self._schedule_preview()
        )

        # Blend threshold
        bt_frame = tk.Frame(panel)
        bt_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(bt_frame, text="Blend Threshold:").pack(side=tk.LEFT)
        self.blend_thresh_var = tk.IntVar(value=30)
        bt_spin = tk.Spinbox(
            bt_frame, from_=0, to=442, width=5, textvariable=self.blend_thresh_var
        )
        bt_spin.pack(side=tk.LEFT, padx=4)

        # Blend border pixels checkbox
        self.blend_border_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            panel, text="Blend border pixels",
            variable=self.blend_border_var,
            command=self._schedule_preview
        ).pack(padx=8, anchor=tk.W)

        # ─── Global Threshold ───────────────────────────────────────────
        sep_thresh = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep_thresh.pack(fill=tk.X, padx=8, pady=(8, 4))

        gt_frame = tk.Frame(panel)
        gt_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(gt_frame, text="Global Threshold:").pack(side=tk.LEFT)
        self.global_thresh_var = tk.IntVar(value=30)
        gt_spin = tk.Spinbox(
            gt_frame, from_=0, to=442, width=5, textvariable=self.global_thresh_var
        )
        gt_spin.pack(side=tk.LEFT, padx=4)

        self.use_global_thresh_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Use global threshold for all points",
            variable=self.use_global_thresh_var,
            command=self._on_use_global_thresh_toggled
        ).pack(padx=8, anchor=tk.W)

        # ─── Global Feathering ──────────────────────────────────────────
        gf_frame = tk.Frame(panel)
        gf_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(gf_frame, text="Global Feathering:").pack(side=tk.LEFT)
        self.global_feather_var = tk.IntVar(value=0)
        gf_spin = tk.Spinbox(
            gf_frame, from_=-50, to=50, width=5, textvariable=self.global_feather_var
        )
        gf_spin.pack(side=tk.LEFT, padx=4)

        self.use_global_feather_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Use global feathering for all points",
            variable=self.use_global_feather_var,
            command=self._on_use_global_feather_toggled
        ).pack(padx=8, anchor=tk.W)

        # ─── Points List ────────────────────────────────────────────────
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Sample Points:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )
        tk.Label(panel, text="(Click image to add points)", font=("", 8)).pack(
            padx=8, anchor=tk.W
        )

        self._points_list = ReflowingList(panel)
        self._points_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Status label
        self.status_label = tk.Label(panel, text="", font=("", 8), fg="gray")
        self.status_label.pack(padx=8, anchor=tk.W)

        # Preview checkbox
        self._preview_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            panel, text="Live preview",
            variable=self._preview_var,
            command=self._on_preview_toggled
        ).pack(padx=8, anchor=tk.W)

        # Average color preview
        self._avg_color_frame = tk.Frame(panel)
        self._avg_color_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(self._avg_color_frame, text="Avg color:", font=("", 8)).pack(side=tk.LEFT)
        self._avg_swatch = tk.Canvas(self._avg_color_frame, width=20, height=14,
                                     highlightthickness=1, highlightbackground="black")
        self._avg_swatch.pack(side=tk.LEFT, padx=4)
        self._avg_label = tk.Label(self._avg_color_frame, text="—", font=("", 8), fg="gray")
        self._avg_label.pack(side=tk.LEFT)

        # Bottom buttons
        btn_frame = tk.Frame(panel)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)

        tk.Button(btn_frame, text="Clear Points", command=self._clear_points).pack(
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
        self._source_image = image

    def add_point(self, img_x, img_y):
        """Add a sample point and trigger preview."""
        try:
            threshold = self.global_thresh_var.get()
        except tk.TclError:
            threshold = 30
        try:
            feathering = self.global_feather_var.get()
        except tk.TclError:
            feathering = 0

        # Get the pixel color for the swatch
        color = (128, 128, 128)  # fallback
        if self._source_image is not None:
            import numpy as np
            arr = np.array(self._source_image.convert("RGB"))
            h, w = arr.shape[:2]
            if 0 <= img_x < w and 0 <= img_y < h:
                color = tuple(arr[img_y, img_x])

        point = {"x": img_x, "y": img_y, "threshold": threshold, "feathering": feathering}
        self.points.append(point)
        self._point_colors.append(color)
        self._refresh_points_list()
        self._schedule_preview()

    def reset(self):
        self._cancel_processing()
        self.points = []
        self._point_colors = []
        self._preview_result = None
        self._refresh_points_list()
        self._update_status("")
        self._avg_swatch.delete("all")
        self._avg_label.config(text="—")

    def _update_status(self, text):
        self.status_label.config(text=text)
        if self._on_status_changed:
            status = text if text else "Ready"
            self._on_status_changed(status)

    # ─── Global Threshold Callbacks ─────────────────────────────────────

    def _on_use_global_thresh_toggled(self):
        self._refresh_points_list()
        if self.use_global_thresh_var.get():
            self._schedule_preview()

    def _on_global_thresh_changed(self):
        if self.use_global_thresh_var.get():
            self._schedule_preview()

    # ─── Global Feathering Callbacks ────────────────────────────────────

    def _on_use_global_feather_toggled(self):
        self._refresh_points_list()
        if self.use_global_feather_var.get():
            self._schedule_preview()

    def _on_global_feather_changed(self):
        if self.use_global_feather_var.get():
            self._schedule_preview()

    # ─── Points List UI ─────────────────────────────────────────────────

    def _refresh_points_list(self):
        self._points_list.clear()

        use_global_thresh = self.use_global_thresh_var.get()
        use_global_feather = self.use_global_feather_var.get()

        for i, pt in enumerate(self.points):
            frame = self._points_list.new_card(bd=1, relief=tk.GROOVE)

            # Header with color swatch
            header = tk.Frame(frame)
            header.pack(fill=tk.X, padx=4, pady=2)

            # Color swatch
            color = self._point_colors[i] if i < len(self._point_colors) else (128, 128, 128)
            hex_color = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            swatch = tk.Canvas(header, width=14, height=14, highlightthickness=1,
                               highlightbackground="black")
            swatch.pack(side=tk.LEFT, padx=(0, 4))
            swatch.create_rectangle(0, 0, 14, 14, fill=hex_color, outline="")

            tk.Label(header, text=f"#{i+1} ({pt['x']}, {pt['y']})", font=("", 9)).pack(
                side=tk.LEFT
            )
            tk.Button(
                header, text="✕", font=("", 8), bd=0,
                command=lambda idx=i: self._remove_point(idx)
            ).pack(side=tk.RIGHT)

            # Threshold
            t_frame = tk.Frame(frame)
            t_frame.pack(fill=tk.X, padx=4)
            tk.Label(t_frame, text="Thresh:", font=("", 8)).pack(side=tk.LEFT)
            t_var = tk.IntVar(value=pt["threshold"])
            thresh_state = tk.DISABLED if use_global_thresh else tk.NORMAL
            t_spin = tk.Spinbox(
                t_frame, from_=0, to=442, width=4, textvariable=t_var,
                state=thresh_state
            )
            t_spin.pack(side=tk.LEFT, padx=2)
            if not use_global_thresh:
                t_var.trace_add("write", lambda *_, idx=i, v=t_var: self._update_threshold(idx, v))

            # Feathering
            f_frame = tk.Frame(frame)
            f_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
            tk.Label(f_frame, text="Feather:", font=("", 8)).pack(side=tk.LEFT)
            f_var = tk.IntVar(value=pt["feathering"])
            feather_state = tk.DISABLED if use_global_feather else tk.NORMAL
            f_spin = tk.Spinbox(
                f_frame, from_=-50, to=50, width=4, textvariable=f_var,
                state=feather_state
            )
            f_spin.pack(side=tk.LEFT, padx=2)
            if not use_global_feather:
                f_var.trace_add("write", lambda *_, idx=i, v=f_var: self._update_feathering(idx, v))

        self._points_list.reflow()

    def _remove_point(self, idx):
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            if idx < len(self._point_colors):
                self._point_colors.pop(idx)
            self._refresh_points_list()
            self._schedule_preview()

    def _update_threshold(self, idx, var):
        if 0 <= idx < len(self.points):
            try:
                val = var.get()
            except (tk.TclError, ValueError):
                return
            if self.points[idx]["threshold"] != val:
                self.points[idx]["threshold"] = val
                self._schedule_preview()

    def _update_feathering(self, idx, var):
        if 0 <= idx < len(self.points):
            try:
                val = var.get()
            except (tk.TclError, ValueError):
                return
            if self.points[idx]["feathering"] != val:
                self.points[idx]["feathering"] = val
                self._schedule_preview()

    def _clear_points(self):
        self._cancel_processing()
        self.points = []
        self._point_colors = []
        self._preview_result = None
        self._refresh_points_list()
        self._update_status("")
        self._avg_swatch.delete("all")
        self._avg_label.config(text="—")
        self._on_preview_ready(None)

    # ─── Debounced Preview ──────────────────────────────────────────────

    def _on_preview_toggled(self):
        if self._preview_var.get():
            self._schedule_preview()
        else:
            self._cancel_processing()
            self._on_preview_ready(None)

    def _schedule_preview(self):
        if self._debounce_id is not None:
            self.parent_frame.after_cancel(self._debounce_id)
            self._debounce_id = None

        self._cancel_processing()

        if not self._preview_var.get():
            return

        if not self.points or self._source_image is None:
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

        try:
            blend_threshold = self.blend_thresh_var.get()
        except tk.TclError:
            blend_threshold = 30

        distance_metric = self.distance_metric_var.get()
        blend_border = self.blend_border_var.get()

        points_snapshot = copy.deepcopy(self.points)

        # Apply global overrides
        if self.use_global_thresh_var.get():
            try:
                global_thresh = self.global_thresh_var.get()
            except tk.TclError:
                global_thresh = 30
            for pt in points_snapshot:
                pt["threshold"] = global_thresh

        if self.use_global_feather_var.get():
            try:
                global_feather = self.global_feather_var.get()
            except tk.TclError:
                global_feather = 0
            for pt in points_snapshot:
                pt["feathering"] = global_feather

        source_image = self._source_image.copy()
        cancel_event = self._cancel_event

        self._update_status("Processing...")

        def worker():
            result = process_uniform_color(
                source_image, points_snapshot, blend_threshold,
                distance_metric=distance_metric,
                blend_border=blend_border,
                cancel_event=cancel_event
            )
            if not cancel_event.is_set() and result is not None:
                self.parent_frame.after(0, lambda: self._on_worker_done(result))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_worker_done(self, result):
        self._preview_result = result
        self._update_status("Preview ready")
        self._update_avg_swatch()
        self._on_preview_ready(result)

    def _update_avg_swatch(self):
        """Update the average color swatch display.

        Since each mask gets its own average, show the seed point color
        of the most recently added point as a reference.
        """
        if self._source_image is None or not self.points:
            self._avg_swatch.delete("all")
            self._avg_label.config(text="—")
            return

        # Show the last point's seed color as reference
        last_color = self._point_colors[-1] if self._point_colors else (128, 128, 128)
        hex_color = f"#{last_color[0]:02x}{last_color[1]:02x}{last_color[2]:02x}"
        self._avg_swatch.delete("all")
        self._avg_swatch.create_rectangle(0, 0, 20, 14, fill=hex_color, outline="")
        self._avg_label.config(text=f"{len(self.points)} region(s) processed")

    # ─── Apply / Cancel ─────────────────────────────────────────────────

    def _apply(self):
        self._cancel_processing()
        if self._preview_result is not None:
            self._on_apply(self._preview_result)
        self._preview_result = None

    def _cancel(self):
        self._cancel_processing()
        self._preview_result = None
        self._on_cancel()
