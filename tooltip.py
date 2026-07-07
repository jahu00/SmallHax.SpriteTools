"""Simple tooltip helper for Tkinter widgets."""

import tkinter as tk


class Tooltip:
    """Attach a hover tooltip to a Tkinter widget."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._tip_window = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event=None):
        self._schedule()

    def _on_leave(self, _event=None):
        self._unschedule()
        self._hide()

    def _schedule(self):
        self._unschedule()
        self._after_id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4

        self._tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("", 9),
            padx=4,
            pady=2,
        )
        label.pack()

    def _hide(self):
        if self._tip_window is not None:
            self._tip_window.destroy()
            self._tip_window = None
