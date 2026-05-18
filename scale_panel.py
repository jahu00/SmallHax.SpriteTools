"""Scaling tool side panel UI with live preview and preprocessing filters."""

import tkinter as tk
from tkinter import ttk
import threading
import copy

from scaling import scale_image, scale_tileset, RESAMPLE_METHODS


class ScalePanel:
    """Side panel for the scaling tool.

    Provides:
    - Fixed resolution scaling
    - Percentage-based scaling
    - Aspect ratio lock
    - Multiple resampling methods
    - Tileset scaling mode
    - Reorderable preprocessing filters (erode, dilate, frequency, blur)
    - Live preview with debouncing
    """

    DEBOUNCE_MS = 400

    def __init__(self, parent_frame, on_preview_ready, on_apply, on_cancel,
                 on_status_changed=None):
        """Initialize the panel.

        Args:
            parent_frame: Parent tk.Frame to build UI into.
            on_preview_ready: Callback(image) when preview is computed.
            on_apply: Callback(image) when user applies scaling.
            on_cancel: Callback() when user cancels.
            on_status_changed: Callback(text) for status updates.
        """
        self.parent_frame = parent_frame
        self._on_preview_ready = on_preview_ready
        self._on_apply = on_apply
        self._on_cancel = on_cancel
        self._on_status_changed = on_status_changed

        # State
        self._source_image = None
        self._preview_result = None
        self._updating_from_code = False  # prevent recursive trace callbacks

        # Threading
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._debounce_id = None

        # Filter list: each entry is a dict with type, kernel_size, kernel_shape, enabled
        self._filters = [
            {"type": "erode", "kernel_size": 1, "kernel_shape": "square", "enabled": False},
            {"type": "dilate", "kernel_size": 1, "kernel_shape": "square", "enabled": False},
            {"type": "frequency", "kernel_size": 1, "kernel_shape": "square", "enabled": False},
            {"type": "blur", "kernel_size": 1, "kernel_shape": "square", "enabled": False},
        ]

        self._build_ui()

    def _build_ui(self):
        panel = self.parent_frame

        # Title
        tk.Label(panel, text="Scale Image", font=("", 11, "bold")).pack(
            pady=(8, 4), padx=8, anchor=tk.W
        )

        # ─── Mode Selection ─────────────────────────────────────────────
        mode_frame = tk.Frame(panel)
        mode_frame.pack(fill=tk.X, padx=8, pady=4)

        self._mode_var = tk.StringVar(value="fixed")
        tk.Radiobutton(mode_frame, text="Fixed Size", variable=self._mode_var,
                       value="fixed", command=self._on_mode_changed).pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="Percentage", variable=self._mode_var,
                       value="percent", command=self._on_mode_changed).pack(side=tk.LEFT, padx=(8, 0))
        tk.Radiobutton(mode_frame, text="Tileset", variable=self._mode_var,
                       value="tileset", command=self._on_mode_changed).pack(side=tk.LEFT, padx=(8, 0))

        # ─── Fixed Size Controls ────────────────────────────────────────
        self._fixed_frame = tk.Frame(panel)
        self._fixed_frame.pack(fill=tk.X, padx=8, pady=4)

        tk.Label(self._fixed_frame, text="Width:", font=("", 9)).grid(row=0, column=0, sticky=tk.W)
        self._width_var = tk.IntVar(value=256)
        self._width_spin = tk.Spinbox(self._fixed_frame, from_=1, to=99999, width=6,
                                      textvariable=self._width_var)
        self._width_spin.grid(row=0, column=1, padx=4)

        tk.Label(self._fixed_frame, text="Height:", font=("", 9)).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        self._height_var = tk.IntVar(value=256)
        self._height_spin = tk.Spinbox(self._fixed_frame, from_=1, to=99999, width=6,
                                       textvariable=self._height_var)
        self._height_spin.grid(row=0, column=3, padx=4)

        # ─── Percentage Controls ────────────────────────────────────────
        self._percent_frame = tk.Frame(panel)
        # Not packed by default

        tk.Label(self._percent_frame, text="W %:", font=("", 9)).grid(row=0, column=0, sticky=tk.W)
        self._percent_w_var = tk.IntVar(value=100)
        self._percent_w_spin = tk.Spinbox(self._percent_frame, from_=1, to=10000, width=6,
                                          textvariable=self._percent_w_var)
        self._percent_w_spin.grid(row=0, column=1, padx=4)

        tk.Label(self._percent_frame, text="H %:", font=("", 9)).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        self._percent_h_var = tk.IntVar(value=100)
        self._percent_h_spin = tk.Spinbox(self._percent_frame, from_=1, to=10000, width=6,
                                          textvariable=self._percent_h_var)
        self._percent_h_spin.grid(row=0, column=3, padx=4)

        # ─── Tileset Controls ───────────────────────────────────────────
        self._tileset_frame = tk.Frame(panel)
        # Not packed by default

        tk.Label(self._tileset_frame, text="Grid Cols:", font=("", 9)).grid(row=0, column=0, sticky=tk.W)
        self._tile_cols_var = tk.IntVar(value=3)
        tk.Spinbox(self._tileset_frame, from_=1, to=999, width=4,
                   textvariable=self._tile_cols_var).grid(row=0, column=1, padx=4)

        tk.Label(self._tileset_frame, text="Grid Rows:", font=("", 9)).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        self._tile_rows_var = tk.IntVar(value=2)
        tk.Spinbox(self._tileset_frame, from_=1, to=999, width=4,
                   textvariable=self._tile_rows_var).grid(row=0, column=3, padx=4)

        tk.Label(self._tileset_frame, text="Tile W:", font=("", 9)).grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._tile_w_var = tk.IntVar(value=64)
        tk.Spinbox(self._tileset_frame, from_=1, to=99999, width=5,
                   textvariable=self._tile_w_var).grid(row=1, column=1, padx=4, pady=(4, 0))

        tk.Label(self._tileset_frame, text="Tile H:", font=("", 9)).grid(row=1, column=2, sticky=tk.W, padx=(8, 0), pady=(4, 0))
        self._tile_h_var = tk.IntVar(value=64)
        tk.Spinbox(self._tileset_frame, from_=1, to=99999, width=5,
                   textvariable=self._tile_h_var).grid(row=1, column=3, padx=4, pady=(4, 0))

        # ─── Aspect Ratio ───────────────────────────────────────────────
        self._keep_aspect_var = tk.BooleanVar(value=True)
        self._aspect_check = tk.Checkbutton(
            panel, text="Keep aspect ratio",
            variable=self._keep_aspect_var,
            command=self._on_aspect_toggled
        )
        self._aspect_check.pack(padx=8, anchor=tk.W, pady=(4, 0))

        # ─── Resampling Method ──────────────────────────────────────────
        sep1 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep1.pack(fill=tk.X, padx=8, pady=(8, 4))

        resample_frame = tk.Frame(panel)
        resample_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(resample_frame, text="Resample:", font=("", 9)).pack(side=tk.LEFT)
        self._resample_var = tk.StringVar(value="Lanczos")
        ttk.Combobox(
            resample_frame, textvariable=self._resample_var,
            values=list(RESAMPLE_METHODS.keys()), state="readonly", width=10
        ).pack(side=tk.LEFT, padx=4)

        # ─── Info Label ─────────────────────────────────────────────────
        self._info_var = tk.StringVar(value="")
        tk.Label(panel, textvariable=self._info_var, font=("", 8), fg="gray").pack(
            padx=8, anchor=tk.W, pady=(4, 0)
        )

        # ─── Preprocessing Filters ──────────────────────────────────────
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(panel, text="Preprocessing Filters:", font=("", 10)).pack(
            pady=(4, 2), padx=8, anchor=tk.W
        )
        tk.Label(panel, text="(applied before scaling, drag to reorder)", font=("", 7), fg="gray").pack(
            padx=8, anchor=tk.W
        )

        self._filters_frame = tk.Frame(panel)
        self._filters_frame.pack(fill=tk.X, padx=8, pady=4)

        self._build_filters_ui()

        # ─── Preview Checkbox ───────────────────────────────────────────
        sep3 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep3.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._preview_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            panel, text="Live preview",
            variable=self._preview_var,
            command=self._on_preview_toggled
        ).pack(padx=8, anchor=tk.W)

        # Status label
        self._status_label = tk.Label(panel, text="", font=("", 8), fg="gray")
        self._status_label.pack(padx=8, anchor=tk.W, pady=(4, 0))

        # ─── Bottom Buttons ─────────────────────────────────────────────
        btn_frame = tk.Frame(panel)
        btn_frame.pack(fill=tk.X, padx=8, pady=8, side=tk.BOTTOM)

        tk.Button(btn_frame, text="Apply", command=self._apply).pack(
            side=tk.RIGHT, padx=2
        )
        tk.Button(btn_frame, text="Cancel", command=self._cancel).pack(
            side=tk.RIGHT, padx=2
        )

        # ─── Register Traces ────────────────────────────────────────────
        self._width_var.trace_add("write", lambda *_: self._on_width_changed())
        self._height_var.trace_add("write", lambda *_: self._on_height_changed())
        self._percent_w_var.trace_add("write", lambda *_: self._on_percent_w_changed())
        self._percent_h_var.trace_add("write", lambda *_: self._on_percent_h_changed())
        self._tile_cols_var.trace_add("write", lambda *_: self._schedule_preview())
        self._tile_rows_var.trace_add("write", lambda *_: self._schedule_preview())
        self._tile_w_var.trace_add("write", lambda *_: self._on_tile_w_changed())
        self._tile_h_var.trace_add("write", lambda *_: self._on_tile_h_changed())
        self._resample_var.trace_add("write", lambda *_: self._schedule_preview())

    # ─── Filter UI ──────────────────────────────────────────────────────

    def _build_filters_ui(self):
        """Build the filter list UI with enable checkboxes and reorder buttons."""
        for widget in self._filters_frame.winfo_children():
            widget.destroy()

        for i, f in enumerate(self._filters):
            row_frame = tk.Frame(self._filters_frame, bd=1, relief=tk.GROOVE)
            row_frame.pack(fill=tk.X, pady=1)

            # Reorder buttons
            btn_frame = tk.Frame(row_frame)
            btn_frame.pack(side=tk.LEFT, padx=2)

            up_btn = tk.Button(btn_frame, text="▲", font=("", 7), width=2,
                               command=lambda idx=i: self._move_filter_up(idx))
            up_btn.pack(side=tk.TOP)
            if i == 0:
                up_btn.config(state=tk.DISABLED)

            down_btn = tk.Button(btn_frame, text="▼", font=("", 7), width=2,
                                 command=lambda idx=i: self._move_filter_down(idx))
            down_btn.pack(side=tk.TOP)
            if i == len(self._filters) - 1:
                down_btn.config(state=tk.DISABLED)

            # Enable checkbox and filter name
            content_frame = tk.Frame(row_frame)
            content_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            enabled_var = tk.BooleanVar(value=f["enabled"])
            chk = tk.Checkbutton(
                content_frame, text=f["type"].capitalize(),
                variable=enabled_var, font=("", 9),
                command=lambda idx=i, v=enabled_var: self._on_filter_enabled_changed(idx, v)
            )
            chk.pack(side=tk.LEFT)

            # Kernel size (n value, actual size = 2*n+1)
            tk.Label(content_frame, text="n:", font=("", 8)).pack(side=tk.LEFT, padx=(8, 0))
            ks_var = tk.IntVar(value=f["kernel_size"])
            ks_spin = tk.Spinbox(content_frame, from_=1, to=20, width=3,
                                 textvariable=ks_var)
            ks_spin.pack(side=tk.LEFT, padx=2)
            ks_var.trace_add("write", lambda *_, idx=i, v=ks_var: self._on_filter_kernel_changed(idx, v))

            # Kernel shape
            shape_var = tk.StringVar(value=f["kernel_shape"])
            shape_combo = ttk.Combobox(content_frame, textvariable=shape_var,
                                       values=["square", "round"], state="readonly", width=6)
            shape_combo.pack(side=tk.LEFT, padx=2)
            shape_var.trace_add("write", lambda *_, idx=i, v=shape_var: self._on_filter_shape_changed(idx, v))

    def _move_filter_up(self, idx):
        if idx > 0:
            self._filters[idx], self._filters[idx - 1] = self._filters[idx - 1], self._filters[idx]
            self._build_filters_ui()
            self._schedule_preview()

    def _move_filter_down(self, idx):
        if idx < len(self._filters) - 1:
            self._filters[idx], self._filters[idx + 1] = self._filters[idx + 1], self._filters[idx]
            self._build_filters_ui()
            self._schedule_preview()

    def _on_filter_enabled_changed(self, idx, var):
        try:
            self._filters[idx]["enabled"] = var.get()
        except tk.TclError:
            return
        self._schedule_preview()

    def _on_filter_kernel_changed(self, idx, var):
        try:
            val = var.get()
        except (tk.TclError, ValueError):
            return
        self._filters[idx]["kernel_size"] = val
        if self._filters[idx]["enabled"]:
            self._schedule_preview()

    def _on_filter_shape_changed(self, idx, var):
        try:
            val = var.get()
        except (tk.TclError, ValueError):
            return
        self._filters[idx]["kernel_shape"] = val
        if self._filters[idx]["enabled"]:
            self._schedule_preview()

    # ─── Mode Switching ─────────────────────────────────────────────────

    def _on_mode_changed(self):
        mode = self._mode_var.get()
        self._fixed_frame.pack_forget()
        self._percent_frame.pack_forget()
        self._tileset_frame.pack_forget()

        if mode == "fixed":
            self._fixed_frame.pack(fill=tk.X, padx=8, pady=4, after=self._get_mode_anchor())
        elif mode == "percent":
            self._percent_frame.pack(fill=tk.X, padx=8, pady=4, after=self._get_mode_anchor())
        elif mode == "tileset":
            self._tileset_frame.pack(fill=tk.X, padx=8, pady=4, after=self._get_mode_anchor())

        self._aspect_check.config(state=tk.NORMAL)
        self._schedule_preview()

    def _get_mode_anchor(self):
        """Get the widget after which mode-specific frames should be packed."""
        # Find the mode_frame in parent's children
        for widget in self.parent_frame.winfo_children():
            if isinstance(widget, tk.Frame):
                # Check if it contains radiobuttons (the mode frame)
                children = widget.winfo_children()
                if children and isinstance(children[0], tk.Radiobutton):
                    return widget
        return None

    # ─── Aspect Ratio Logic ─────────────────────────────────────────────

    def _on_aspect_toggled(self):
        if self._keep_aspect_var.get() and self._source_image is not None:
            mode = self._mode_var.get()
            if mode == "fixed":
                self._on_width_changed()
            elif mode == "percent":
                self._on_percent_w_changed()
            elif mode == "tileset":
                self._on_tile_w_changed()
        self._schedule_preview()

    def _on_width_changed(self):
        if self._updating_from_code:
            return
        if self._mode_var.get() != "fixed":
            self._schedule_preview()
            return
        if self._keep_aspect_var.get() and self._source_image is not None:
            try:
                w = self._width_var.get()
            except (tk.TclError, ValueError):
                return
            iw, ih = self._source_image.size
            if iw > 0:
                new_h = max(1, int(w * ih / iw))
                self._updating_from_code = True
                self._height_var.set(new_h)
                self._updating_from_code = False
        self._schedule_preview()

    def _on_height_changed(self):
        if self._updating_from_code:
            return
        if self._mode_var.get() != "fixed":
            self._schedule_preview()
            return
        if self._keep_aspect_var.get() and self._source_image is not None:
            try:
                h = self._height_var.get()
            except (tk.TclError, ValueError):
                return
            iw, ih = self._source_image.size
            if ih > 0:
                new_w = max(1, int(h * iw / ih))
                self._updating_from_code = True
                self._width_var.set(new_w)
                self._updating_from_code = False
        self._schedule_preview()

    def _on_percent_w_changed(self):
        if self._updating_from_code:
            return
        if self._mode_var.get() != "percent":
            self._schedule_preview()
            return
        if self._keep_aspect_var.get():
            try:
                pw = self._percent_w_var.get()
            except (tk.TclError, ValueError):
                return
            self._updating_from_code = True
            self._percent_h_var.set(pw)
            self._updating_from_code = False
        self._schedule_preview()

    def _on_percent_h_changed(self):
        if self._updating_from_code:
            return
        if self._mode_var.get() != "percent":
            self._schedule_preview()
            return
        if self._keep_aspect_var.get():
            try:
                ph = self._percent_h_var.get()
            except (tk.TclError, ValueError):
                return
            self._updating_from_code = True
            self._percent_w_var.set(ph)
            self._updating_from_code = False
        self._schedule_preview()

    def _on_tile_w_changed(self):
        if self._updating_from_code:
            return
        if self._mode_var.get() != "tileset":
            self._schedule_preview()
            return
        if self._keep_aspect_var.get() and self._source_image is not None:
            try:
                tile_w = self._tile_w_var.get()
                tile_cols = max(1, self._tile_cols_var.get())
                tile_rows = max(1, self._tile_rows_var.get())
            except (tk.TclError, ValueError):
                return
            iw, ih = self._source_image.size
            # Compute source tile aspect ratio
            src_tile_w = iw / tile_cols
            src_tile_h = ih / tile_rows
            if src_tile_w > 0:
                new_tile_h = max(1, int(tile_w * src_tile_h / src_tile_w))
                self._updating_from_code = True
                self._tile_h_var.set(new_tile_h)
                self._updating_from_code = False
        self._schedule_preview()

    def _on_tile_h_changed(self):
        if self._updating_from_code:
            return
        if self._mode_var.get() != "tileset":
            self._schedule_preview()
            return
        if self._keep_aspect_var.get() and self._source_image is not None:
            try:
                tile_h = self._tile_h_var.get()
                tile_cols = max(1, self._tile_cols_var.get())
                tile_rows = max(1, self._tile_rows_var.get())
            except (tk.TclError, ValueError):
                return
            iw, ih = self._source_image.size
            # Compute source tile aspect ratio
            src_tile_w = iw / tile_cols
            src_tile_h = ih / tile_rows
            if src_tile_h > 0:
                new_tile_w = max(1, int(tile_h * src_tile_w / src_tile_h))
                self._updating_from_code = True
                self._tile_w_var.set(new_tile_w)
                self._updating_from_code = False
        self._schedule_preview()

    # ─── Public Interface ───────────────────────────────────────────────

    def set_source_image(self, image):
        """Set the source image and update defaults."""
        self._source_image = image
        if image is not None:
            iw, ih = image.size
            self._updating_from_code = True
            self._width_var.set(iw)
            self._height_var.set(ih)
            self._updating_from_code = False
            self._update_info()

    def reset(self):
        """Reset all state to defaults."""
        self._cancel_processing()
        self._source_image = None
        self._preview_result = None
        self._mode_var.set("fixed")
        self._updating_from_code = True
        self._width_var.set(256)
        self._height_var.set(256)
        self._percent_w_var.set(100)
        self._percent_h_var.set(100)
        self._tile_cols_var.set(3)
        self._tile_rows_var.set(2)
        self._tile_w_var.set(64)
        self._tile_h_var.set(64)
        self._updating_from_code = False
        self._keep_aspect_var.set(True)
        self._resample_var.set("Lanczos")
        self._preview_var.set(True)
        for f in self._filters:
            f["enabled"] = False
            f["kernel_size"] = 1
            f["kernel_shape"] = "square"
        self._build_filters_ui()
        self._on_mode_changed()
        self._update_status("")
        self._info_var.set("")

    # ─── Info ───────────────────────────────────────────────────────────

    def _update_info(self):
        if self._source_image is None:
            self._info_var.set("")
            return
        iw, ih = self._source_image.size
        mode = self._mode_var.get()
        try:
            tw, th = self._get_target_size()
            self._info_var.set(f"Source: {iw}×{ih} → Target: {tw}×{th}")
        except Exception:
            self._info_var.set(f"Source: {iw}×{ih}")

    def _get_target_size(self):
        """Compute target width and height based on current mode."""
        if self._source_image is None:
            return (256, 256)

        mode = self._mode_var.get()
        iw, ih = self._source_image.size

        if mode == "fixed":
            tw = self._width_var.get()
            th = self._height_var.get()
            return (max(1, tw), max(1, th))
        elif mode == "percent":
            pct_w = self._percent_w_var.get()
            pct_h = self._percent_h_var.get()
            tw = max(1, int(iw * pct_w / 100))
            th = max(1, int(ih * pct_h / 100))
            return (tw, th)
        elif mode == "tileset":
            cols = self._tile_cols_var.get()
            rows = self._tile_rows_var.get()
            tile_w = self._tile_w_var.get()
            tile_h = self._tile_h_var.get()
            return (max(1, cols * tile_w), max(1, rows * tile_h))

        return (iw, ih)

    # ─── Preview ────────────────────────────────────────────────────────

    def _on_preview_toggled(self):
        if self._preview_var.get():
            self._schedule_preview()
        else:
            self._on_preview_ready(None)

    def _schedule_preview(self):
        self._update_info()

        if self._debounce_id is not None:
            self.parent_frame.after_cancel(self._debounce_id)
            self._debounce_id = None

        self._cancel_processing()

        if not self._preview_var.get():
            return

        if self._source_image is None:
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
        cancel_event = self._cancel_event
        resample_method = self._resample_var.get()

        # Gather enabled filters in order
        filters = []
        for f in self._filters:
            if f["enabled"]:
                n = f["kernel_size"]
                actual_size = 2 * n + 1
                filters.append({
                    "type": f["type"],
                    "kernel_size": actual_size,
                    "kernel_shape": f["kernel_shape"],
                })

        mode = self._mode_var.get()

        try:
            if mode == "tileset":
                tile_cols = max(1, self._tile_cols_var.get())
                tile_rows = max(1, self._tile_rows_var.get())
                tile_w = max(1, self._tile_w_var.get())
                tile_h = max(1, self._tile_h_var.get())
            else:
                tw, th = self._get_target_size()
        except (tk.TclError, ValueError):
            self._update_status("Invalid parameters")
            return

        self._update_status("Processing...")

        def worker():
            if mode == "tileset":
                result = scale_tileset(
                    source_image, tile_cols, tile_rows, tile_w, tile_h,
                    resample_method, filters if filters else None, cancel_event
                )
            else:
                result = scale_image(
                    source_image, tw, th, resample_method,
                    filters if filters else None, cancel_event
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
        """Apply the scaling."""
        self._cancel_processing()
        if self._preview_result is not None:
            self._on_apply(self._preview_result)
        elif self._source_image is not None:
            # Compute synchronously
            self._update_status("Applying...")
            resample_method = self._resample_var.get()
            filters = []
            for f in self._filters:
                if f["enabled"]:
                    n = f["kernel_size"]
                    actual_size = 2 * n + 1
                    filters.append({
                        "type": f["type"],
                        "kernel_size": actual_size,
                        "kernel_shape": f["kernel_shape"],
                    })

            mode = self._mode_var.get()
            try:
                if mode == "tileset":
                    result = scale_tileset(
                        self._source_image,
                        max(1, self._tile_cols_var.get()),
                        max(1, self._tile_rows_var.get()),
                        max(1, self._tile_w_var.get()),
                        max(1, self._tile_h_var.get()),
                        resample_method,
                        filters if filters else None,
                    )
                else:
                    tw, th = self._get_target_size()
                    result = scale_image(
                        self._source_image, tw, th, resample_method,
                        filters if filters else None,
                    )
            except Exception:
                result = None

            if result is not None:
                self._on_apply(result)
        self._preview_result = None

    def _cancel(self):
        """Cancel and return to cursor tool."""
        self._cancel_processing()
        self._preview_result = None
        self._on_cancel()

    # ─── Helpers ────────────────────────────────────────────────────────

    def _update_status(self, text):
        self._status_label.config(text=text)
        if self._on_status_changed:
            status = text if text else "Ready"
            self._on_status_changed(status)
