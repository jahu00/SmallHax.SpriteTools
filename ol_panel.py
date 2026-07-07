"""Outline tool side panel UI with debounced threaded preview."""

import tkinter as tk
from tkinter import ttk, colorchooser
import threading
import copy

from outline import compute_outline


class OutlinePanel:
    """Side panel for the outline tool.

    The user clicks on background pixels (like BG removal), then the tool
    computes an outline around the foreground with configurable thickness,
    color, and placement (behind or above).
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
        self._point_colors = []

        # Threading
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._debounce_id = None

        self._build_ui()

        # Register traces after UI is built
        self._thickness_var.trace_add("write", lambda *_: self._schedule_preview())
        self._global_thresh_var.trace_add("write", lambda *_: self._on_global_thresh_changed())
        self._feathering_var.trace_add("write", lambda *_: self._schedule_preview())
        self._smooth_radius_var.trace_add("write", lambda *_: self._on_smooth_radius_changed())

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Outline", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # ─── Outline Settings ───────────────────────────────────────────
        tk.Label(panel, text="Outline Settings:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )

        # Thickness
        thick_frame = tk.Frame(panel)
        thick_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(thick_frame, text="Thickness:", font=("", 8)).pack(side=tk.LEFT)
        self._thickness_var = tk.IntVar(value=3)
        tk.Spinbox(thick_frame, from_=1, to=100, width=4,
                   textvariable=self._thickness_var).pack(side=tk.LEFT, padx=4)

        # Color
        color_frame = tk.Frame(panel)
        color_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(color_frame, text="Color:", font=("", 8)).pack(side=tk.LEFT)

        self._outline_color = (0, 0, 0)  # Default black
        self._color_swatch = tk.Canvas(color_frame, width=20, height=20,
                                       highlightthickness=1, highlightbackground="gray",
                                       cursor="hand2")
        self._color_swatch.pack(side=tk.LEFT, padx=4)
        self._color_swatch.create_rectangle(0, 0, 20, 20, fill="#000000", outline="")
        self._color_swatch.bind("<Button-1>", lambda e: self._pick_color())

        tk.Button(color_frame, text="Pick...", font=("", 8),
                  command=self._pick_color).pack(side=tk.LEFT, padx=2)

        # Mode (behind / above)
        mode_frame = tk.Frame(panel)
        mode_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(mode_frame, text="Placement:", font=("", 8)).pack(side=tk.LEFT)
        self._mode_var = tk.StringVar(value="behind")
        self._mode_dropdown = ttk.Combobox(
            mode_frame, textvariable=self._mode_var,
            values=["behind", "above", "instead"], state="readonly", width=8
        )
        self._mode_dropdown.pack(side=tk.LEFT, padx=4)
        self._mode_dropdown.bind("<<ComboboxSelected>>", lambda e: self._schedule_preview())

        # ─── Threshold ──────────────────────────────────────────────────
        sep1 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep1.pack(fill=tk.X, padx=8, pady=(8, 4))

        gt_frame = tk.Frame(panel)
        gt_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(gt_frame, text="Threshold:", font=("", 8)).pack(side=tk.LEFT)
        self._global_thresh_var = tk.IntVar(value=30)
        tk.Spinbox(gt_frame, from_=0, to=442, width=5,
                   textvariable=self._global_thresh_var).pack(side=tk.LEFT, padx=4)

        # Feathering
        gf_frame = tk.Frame(panel)
        gf_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(gf_frame, text="Feathering:", font=("", 8)).pack(side=tk.LEFT)
        self._feathering_var = tk.IntVar(value=0)
        tk.Spinbox(gf_frame, from_=-50, to=50, width=5,
                   textvariable=self._feathering_var).pack(side=tk.LEFT, padx=4)

        # Smoothing
        self._smooth_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Smooth outline", variable=self._smooth_var,
            command=self._on_smooth_toggled, font=("", 8)
        ).pack(padx=8, anchor=tk.W, pady=(4, 0))

        smooth_frame = tk.Frame(panel)
        smooth_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(smooth_frame, text="Radius:", font=("", 8)).pack(side=tk.LEFT)
        self._smooth_radius_var = tk.IntVar(value=2)
        self._smooth_radius_spin = tk.Spinbox(
            smooth_frame, from_=1, to=50, width=4,
            textvariable=self._smooth_radius_var, state=tk.DISABLED
        )
        self._smooth_radius_spin.pack(side=tk.LEFT, padx=4)

        # Anti-aliasing
        self._antialias_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Anti-aliasing", variable=self._antialias_var,
            command=self._schedule_preview, font=("", 8)
        ).pack(padx=8, anchor=tk.W, pady=(4, 0))

        # ─── Preview checkbox ───────────────────────────────────────────
        self._preview_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            panel, text="Live preview",
            variable=self._preview_var,
            command=self._on_preview_toggled
        ).pack(padx=8, anchor=tk.W, pady=(4, 0))

        # ─── Points List ────────────────────────────────────────────────
        sep3 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep3.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Background Points:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )
        tk.Label(panel, text="(Click image to add points)", font=("", 8)).pack(
            padx=8, anchor=tk.W
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
                scrollregion=self._points_canvas.bbox("all"))
        )
        self._points_canvas.create_window((0, 0), window=self._points_inner_frame,
                                          anchor=tk.NW)
        self._points_canvas.configure(yscrollcommand=scrollbar.set)

        self._points_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Status label
        self._status_label = tk.Label(panel, text="", font=("", 8), fg="gray")
        self._status_label.pack(padx=8, anchor=tk.W)

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
        """Add a background sample point and trigger preview."""
        try:
            threshold = self._global_thresh_var.get()
        except tk.TclError:
            threshold = 30

        # Get the pixel color for the swatch
        color = (128, 128, 128)
        if self._source_image is not None:
            import numpy as np
            arr = np.array(self._source_image.convert("RGB"))
            h, w = arr.shape[:2]
            if 0 <= img_x < w and 0 <= img_y < h:
                color = tuple(arr[img_y, img_x])

        point = {"x": img_x, "y": img_y, "threshold": threshold, "feathering": 0}
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

    # ─── Color Picker ───────────────────────────────────────────────────

    def _pick_color(self):
        """Open a color chooser dialog."""
        initial = f"#{self._outline_color[0]:02x}{self._outline_color[1]:02x}{self._outline_color[2]:02x}"
        result = colorchooser.askcolor(initialcolor=initial, title="Outline Color")
        if result and result[0]:
            r, g, b = int(result[0][0]), int(result[0][1]), int(result[0][2])
            self._outline_color = (r, g, b)
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            self._color_swatch.delete("all")
            self._color_swatch.create_rectangle(0, 0, 20, 20, fill=hex_color, outline="")
            self._schedule_preview()

    # ─── Threshold ──────────────────────────────────────────────────────

    def _on_global_thresh_changed(self):
        self._schedule_preview()

    # ─── Smoothing ──────────────────────────────────────────────────────

    def _on_smooth_toggled(self):
        """Handle the smooth checkbox toggle."""
        if self._smooth_var.get():
            self._smooth_radius_spin.config(state=tk.NORMAL)
        else:
            self._smooth_radius_spin.config(state=tk.DISABLED)
        self._schedule_preview()

    def _on_smooth_radius_changed(self):
        """Called when smooth radius changes — only trigger if smoothing is enabled."""
        if self._smooth_var.get():
            self._schedule_preview()

    # ─── Points List UI ─────────────────────────────────────────────────

    def _refresh_points_list(self):
        for widget in self._points_inner_frame.winfo_children():
            widget.destroy()

        for i, pt in enumerate(self.points):
            frame = tk.Frame(self._points_inner_frame, bd=1, relief=tk.GROOVE)
            frame.pack(fill=tk.X, pady=2)

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

    def _remove_point(self, idx):
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            if idx < len(self._point_colors):
                self._point_colors.pop(idx)
            self._refresh_points_list()
            self._schedule_preview()

    def _clear_points(self):
        self._cancel_processing()
        self.points = []
        self._point_colors = []
        self._preview_result = None
        self._refresh_points_list()
        self._update_status("")
        self._on_preview_ready(None)

    # ─── Status ─────────────────────────────────────────────────────────

    def _update_status(self, text):
        self._status_label.config(text=text)
        if self._on_status_changed:
            self._on_status_changed(text if text else "Ready")

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
            thickness = max(1, self._thickness_var.get())
        except tk.TclError:
            thickness = 3

        try:
            global_thresh = self._global_thresh_var.get()
        except tk.TclError:
            global_thresh = 30

        try:
            feathering = self._feathering_var.get()
        except tk.TclError:
            feathering = 0

        smooth = self._smooth_var.get()
        try:
            smooth_radius = max(1, self._smooth_radius_var.get())
        except tk.TclError:
            smooth_radius = 2

        antialias = self._antialias_var.get()

        outline_color = self._outline_color
        mode = self._mode_var.get()

        points_snapshot = copy.deepcopy(self.points)
        # Apply global threshold and feathering to all points
        for pt in points_snapshot:
            pt["threshold"] = global_thresh
            pt["feathering"] = feathering

        source_image = self._source_image.copy()
        cancel_event = self._cancel_event

        self._update_status("Processing...")

        def worker():
            result = compute_outline(
                source_image, points_snapshot, thickness, outline_color,
                mode=mode, smooth=smooth, smooth_radius=smooth_radius,
                antialias=antialias, cancel_event=cancel_event
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
        self._cancel_processing()
        if self._preview_result is not None:
            self._on_apply(self._preview_result)
        self._preview_result = None

    def _cancel(self):
        self._cancel_processing()
        self._preview_result = None
        self._on_cancel()
