"""Shared preview background color options for panels."""

import tkinter as tk
from tkinter import ttk

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


class PreviewBgWidget:
    """Reusable widget for solid preview background color selection.

    Provides a checkbox to enable solid background and a color dropdown.
    """

    def __init__(self, parent_frame, on_changed=None):
        """Initialize the widget.

        Args:
            parent_frame: Parent tk.Frame to build into.
            on_changed: Callback() when the background option changes.
        """
        self._on_changed = on_changed

        self.use_solid_bg_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            parent_frame, text="Solid preview background",
            variable=self.use_solid_bg_var,
            command=self._on_option_changed
        ).pack(padx=8, anchor=tk.W)

        bg_color_frame = tk.Frame(parent_frame)
        bg_color_frame.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(bg_color_frame, text="Color:").pack(side=tk.LEFT)
        self.bg_color_var = tk.StringVar(value="White")
        self.bg_color_dropdown = ttk.Combobox(
            bg_color_frame, textvariable=self.bg_color_var,
            values=list(BG_COLORS.keys()), state="readonly", width=8
        )
        self.bg_color_dropdown.pack(side=tk.LEFT, padx=4)
        self.bg_color_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_option_changed())
        self.bg_color_dropdown.config(state=tk.DISABLED)

    def _on_option_changed(self):
        if self.use_solid_bg_var.get():
            self.bg_color_dropdown.config(state="readonly")
        else:
            self.bg_color_dropdown.config(state=tk.DISABLED)
        if self._on_changed:
            self._on_changed()

    def get_preview_bg_color(self):
        """Return the selected background color tuple or None if disabled."""
        if self.use_solid_bg_var.get():
            color_name = self.bg_color_var.get()
            return BG_COLORS.get(color_name, (255, 255, 255))
        return None

    def reset(self):
        """Reset to defaults."""
        self.use_solid_bg_var.set(False)
        self.bg_color_dropdown.config(state=tk.DISABLED)
