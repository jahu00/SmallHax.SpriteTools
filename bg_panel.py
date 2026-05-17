"""Background removal side panel UI with debounced threaded preview."""

import tkinter as tk
from tkinter import ttk
import threading
import copy

from bg_removal import process_background_removal

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


class BgRemovalPanel:
    """Side panel for background removal tool with debounced preview generation."""

    DEBOUNCE_MS = 300

    def __init__(self, parent_frame, on_preview_ready, on_apply, on_cancel,
                 on_status_changed=None):
        """
        Args:
            parent_frame: The tk.Frame to build the panel inside.
            on_preview_ready: Callback(image) called on main thread when preview is done.
            on_apply: Callback(image) called when user clicks Apply.
            on_cancel: Callback() called when user clicks Cancel.
            on_status_changed: Callback(text) called when processing status changes.
        """
        self.parent_frame = parent_frame
        self._on_preview_ready = on_preview_ready
        self._on_apply = on_apply
        self._on_cancel = on_cancel
        self._on_status_changed = on_status_changed

        # State
        self.points = []
        self._source_image = None
        self._preview_result = None

        # Threading
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._debounce_id = None

        self._build_ui()
        # Register traces after UI is fully built to avoid premature callbacks
        self.alpha_thresh_var.trace_add("write", lambda *_: self._schedule_preview())
        self.global_thresh_var.trace_add("write", lambda *_: self._on_global_thresh_changed())
        self.global_feather_var.trace_add("write", lambda *_: self._on_global_feather_changed())

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Background Removal", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # Color space selector
        cs_frame = tk.Frame(panel)
        cs_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(cs_frame, text="Color Space:").pack(side=tk.LEFT)
        self.cs_var = tk.StringVar(value="HSL")
        cs_dropdown = ttk.Combobox(
            cs_frame, textvariable=self.cs_var, values=["HSL", "HSV", "HSI"],
            state="readonly", width=6
        )
        cs_dropdown.pack(side=tk.LEFT, padx=4)
        cs_dropdown.bind("<<ComboboxSelected>>", lambda e: self._schedule_preview())

        # Alpha threshold (decides full-transparent vs partial)
        at_frame = tk.Frame(panel)
        at_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(at_frame, text="Alpha Threshold:").pack(side=tk.LEFT)
        self.alpha_thresh_var = tk.IntVar(value=30)
        at_spin = tk.Spinbox(
            at_frame, from_=0, to=442, width=5, textvariable=self.alpha_thresh_var
        )
        at_spin.pack(side=tk.LEFT, padx=4)
        at_spin.bind("<Return>", lambda e: self._schedule_preview())

        # ─── Global Threshold (default/override for per-point threshold) ─
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
        gt_spin.bind("<Return>", lambda e: self._on_global_thresh_changed())

        # Use global threshold checkbox
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
            gf_frame, from_=0, to=50, width=5, textvariable=self.global_feather_var
        )
        gf_spin.pack(side=tk.LEFT, padx=4)
        gf_spin.bind("<Return>", lambda e: self._on_global_feather_changed())

        # Use global feathering checkbox
        self.use_global_feather_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Use global feathering for all points",
            variable=self.use_global_feather_var,
            command=self._on_use_global_feather_toggled
        ).pack(padx=8, anchor=tk.W)

        # ─── Preview Background ─────────────────────────────────────────
        sep = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, padx=8, pady=(8, 4))

        # Solid background checkbox
        self.use_solid_bg_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel, text="Solid preview background",
            variable=self.use_solid_bg_var,
            command=self._on_bg_option_changed
        ).pack(padx=8, anchor=tk.W)

        # Background color dropdown
        bg_color_frame = tk.Frame(panel)
        bg_color_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(bg_color_frame, text="Color:").pack(side=tk.LEFT)
        self.bg_color_var = tk.StringVar(value="White")
        self.bg_color_dropdown = ttk.Combobox(
            bg_color_frame, textvariable=self.bg_color_var,
            values=list(BG_COLORS.keys()), state="readonly", width=8
        )
        self.bg_color_dropdown.pack(side=tk.LEFT, padx=4)
        self.bg_color_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_bg_option_changed())
        self.bg_color_dropdown.config(state=tk.DISABLED)

        # ─── Points List ────────────────────────────────────────────────
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Sample Points:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )
        tk.Label(panel, text="(Click image to add points)", font=("", 8)).pack(
            padx=8, anchor=tk.W
        )

        # Scrollable point list
        list_frame = tk.Frame(panel)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.points_canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.points_canvas.yview)
        self.points_inner_frame = tk.Frame(self.points_canvas)

        self.points_inner_frame.bind(
            "<Configure>",
            lambda e: self.points_canvas.configure(scrollregion=self.points_canvas.bbox("all"))
        )
        self.points_canvas.create_window((0, 0), window=self.points_inner_frame, anchor=tk.NW)
        self.points_canvas.configure(yscrollcommand=scrollbar.set)

        self.points_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Status label
        self.status_label = tk.Label(panel, text="", font=("", 8), fg="gray")
        self.status_label.pack(padx=8, anchor=tk.W)

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
        """Set the source image for processing."""
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

        point = {"x": img_x, "y": img_y, "threshold": threshold, "feathering": feathering}
        self.points.append(point)
        self._refresh_points_list()
        self._schedule_preview()

    def reset(self):
        """Reset panel state."""
        self._cancel_processing()
        self.points = []
        self._preview_result = None
        self.use_solid_bg_var.set(False)
        self.bg_color_dropdown.config(state=tk.DISABLED)
        self._refresh_points_list()
        self._update_status("")

    def get_preview_bg_color(self):
        """Return the solid background color tuple, or None for checkerboard."""
        if self.use_solid_bg_var.get():
            color_name = self.bg_color_var.get()
            return BG_COLORS.get(color_name, (255, 255, 255))
        return None

    def _update_status(self, text):
        """Update both the panel status label and the main window status bar."""
        self.status_label.config(text=text)
        if self._on_status_changed:
            status = text if text else "Ready"
            self._on_status_changed(status)

    # ─── Background Option Callbacks ────────────────────────────────────

    def _on_bg_option_changed(self):
        """Called when solid bg checkbox or color changes."""
        if self.use_solid_bg_var.get():
            self.bg_color_dropdown.config(state="readonly")
        else:
            self.bg_color_dropdown.config(state=tk.DISABLED)
        # Re-render preview with new background (no reprocessing needed)
        if self._preview_result is not None:
            self._on_preview_ready(self._preview_result)

    # ─── Global Threshold Callbacks ─────────────────────────────────────

    def _on_use_global_thresh_toggled(self):
        """Called when 'use global threshold' checkbox is toggled."""
        self._refresh_points_list()
        if self.use_global_thresh_var.get():
            self._schedule_preview()

    def _on_global_thresh_changed(self):
        """Called when global threshold value changes."""
        if self.use_global_thresh_var.get():
            self._schedule_preview()

    # ─── Global Feathering Callbacks ────────────────────────────────────

    def _on_use_global_feather_toggled(self):
        """Called when 'use global feathering' checkbox is toggled."""
        self._refresh_points_list()
        if self.use_global_feather_var.get():
            self._schedule_preview()

    def _on_global_feather_changed(self):
        """Called when global feathering value changes."""
        if self.use_global_feather_var.get():
            self._schedule_preview()

    # ─── Points List UI ─────────────────────────────────────────────────

    def _refresh_points_list(self):
        for widget in self.points_inner_frame.winfo_children():
            widget.destroy()

        use_global_thresh = self.use_global_thresh_var.get()
        use_global_feather = self.use_global_feather_var.get()

        for i, pt in enumerate(self.points):
            frame = tk.Frame(self.points_inner_frame, bd=1, relief=tk.GROOVE)
            frame.pack(fill=tk.X, pady=2)

            # Header
            header = tk.Frame(frame)
            header.pack(fill=tk.X, padx=4, pady=2)
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
                command=lambda idx=i, v=t_var: self._update_threshold(idx, v),
                state=thresh_state
            )
            t_spin.pack(side=tk.LEFT, padx=2)
            if not use_global_thresh:
                t_spin.bind("<Return>", lambda e, idx=i, v=t_var: self._update_threshold(idx, v))

            # Feathering
            f_frame = tk.Frame(frame)
            f_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
            tk.Label(f_frame, text="Feather:", font=("", 8)).pack(side=tk.LEFT)
            f_var = tk.IntVar(value=pt["feathering"])
            feather_state = tk.DISABLED if use_global_feather else tk.NORMAL
            f_spin = tk.Spinbox(
                f_frame, from_=0, to=50, width=4, textvariable=f_var,
                command=lambda idx=i, v=f_var: self._update_feathering(idx, v),
                state=feather_state
            )
            f_spin.pack(side=tk.LEFT, padx=2)
            if not use_global_feather:
                f_spin.bind(
                    "<Return>", lambda e, idx=i, v=f_var: self._update_feathering(idx, v)
                )

    def _remove_point(self, idx):
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            self._refresh_points_list()
            self._schedule_preview()

    def _update_threshold(self, idx, var):
        if 0 <= idx < len(self.points):
            try:
                self.points[idx]["threshold"] = var.get()
            except tk.TclError:
                return
            self._schedule_preview()

    def _update_feathering(self, idx, var):
        if 0 <= idx < len(self.points):
            try:
                self.points[idx]["feathering"] = var.get()
            except tk.TclError:
                return
            self._schedule_preview()

    def _clear_points(self):
        self._cancel_processing()
        self.points = []
        self._preview_result = None
        self._refresh_points_list()
        self._update_status("")
        self._on_preview_ready(None)

    # ─── Debounced Preview ──────────────────────────────────────────────

    def _schedule_preview(self):
        """Debounce: cancel previous timer, start a new one."""
        if self._debounce_id is not None:
            self.parent_frame.after_cancel(self._debounce_id)
            self._debounce_id = None

        # Cancel any running processing
        self._cancel_processing()

        if not self.points or self._source_image is None:
            self._preview_result = None
            self._on_preview_ready(None)
            self._update_status("")
            return

        self._update_status("Waiting...")
        self._debounce_id = self.parent_frame.after(self.DEBOUNCE_MS, self._start_processing)

    def _cancel_processing(self):
        """Signal the worker thread to stop."""
        self._cancel_event.set()

    def _start_processing(self):
        """Start background processing in a thread."""
        self._debounce_id = None

        # Fresh cancel event for this run
        self._cancel_event = threading.Event()

        try:
            alpha_threshold = self.alpha_thresh_var.get()
        except tk.TclError:
            alpha_threshold = 30
        color_space = self.cs_var.get()

        # Deep copy points so the thread has a stable snapshot
        points_snapshot = copy.deepcopy(self.points)

        # If using global threshold, override all point threshold values
        if self.use_global_thresh_var.get():
            try:
                global_thresh = self.global_thresh_var.get()
            except tk.TclError:
                global_thresh = 30
            for pt in points_snapshot:
                pt["threshold"] = global_thresh

        # If using global feathering, override all point feathering values
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
            result = process_background_removal(
                source_image, points_snapshot, alpha_threshold, color_space,
                cancel_event=cancel_event
            )
            if not cancel_event.is_set() and result is not None:
                self.parent_frame.after(0, lambda: self._on_worker_done(result))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_worker_done(self, result):
        """Called on main thread when worker finishes successfully."""
        self._preview_result = result
        self._update_status("Preview ready")
        self._on_preview_ready(result)

    # ─── Apply / Cancel ─────────────────────────────────────────────────

    def _apply(self):
        """Apply the current preview."""
        self._cancel_processing()
        if self._preview_result is not None:
            self._on_apply(self._preview_result)
        self._preview_result = None

    def _cancel(self):
        """Cancel and discard."""
        self._cancel_processing()
        self._preview_result = None
        self._on_cancel()
