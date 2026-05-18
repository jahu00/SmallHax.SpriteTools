#!/usr/bin/env python3
"""Simple image editor using Tkinter and Pillow."""

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image

from bg_panel import BgRemovalPanel
from cc_panel import ColorCorrectionPanel
from crop_panel import SpriteCropPanel
from image_viewer import ImageViewer


# ─── Main Application ──────────────────────────────────────────────────────

class ImageEditor:
    """Main application class for the image editor."""

    TOOL_CURSOR = "cursor"
    TOOL_BG_REMOVE = "bg_remove"
    TOOL_COLOR_CORRECT = "color_correct"
    TOOL_SPRITE_CROP = "sprite_crop"

    def __init__(self, root):
        self.root = root
        self.root.title("Image Editor")
        self.root.geometry("1024x768")

        # Image state
        self.original_image = None
        self.preview_image = None
        self.reference_image = None

        # Tool state
        self.active_tool = self.TOOL_CURSOR

        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._build_main_area()
        self._bind_events()

    # ─── UI Construction ────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.open_image)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+S", command=self.save_image)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        self.root.config(menu=menubar)

    def _build_toolbar(self):
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.cursor_btn = tk.Button(
            toolbar, text="✥ Cursor", relief=tk.SUNKEN, command=self._select_cursor_tool
        )
        self.cursor_btn.pack(side=tk.LEFT, padx=2, pady=2)

        self.bg_remove_btn = tk.Button(
            toolbar, text="🔲 BG Remove", relief=tk.RAISED, command=self._select_bg_remove_tool
        )
        self.bg_remove_btn.pack(side=tk.LEFT, padx=2, pady=2)

        self.cc_btn = tk.Button(
            toolbar, text="🎨 Color Correct", relief=tk.RAISED,
            command=self._select_color_correct_tool
        )
        self.cc_btn.pack(side=tk.LEFT, padx=2, pady=2)

        self.crop_btn = tk.Button(
            toolbar, text="✂ Sprite Crop", relief=tk.RAISED,
            command=self._select_sprite_crop_tool
        )
        self.crop_btn.pack(side=tk.LEFT, padx=2, pady=2)

        # Zoom indicator label (click to toggle 100% / fit)
        self.zoom_label = tk.Label(toolbar, text="100%", padx=8, cursor="hand2")
        self.zoom_label.pack(side=tk.RIGHT, padx=4, pady=2)
        self.zoom_label.bind("<Button-1>", lambda e: self._toggle_zoom())

    def _build_main_area(self):
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # ─── Single-viewer container (used by cursor and bg_remove tools) ───
        self.single_viewer_frame = tk.Frame(self.main_frame)
        self.single_viewer_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.viewer = ImageViewer(
            self.single_viewer_frame,
            bg_color_func=self._get_bg_color,
        )
        self.viewer.pack(fill=tk.BOTH, expand=True)
        self.viewer.set_on_zoom_changed(self._on_zoom_changed)
        self.viewer.set_on_draw_overlay(self._draw_overlay)

        # Drag-and-drop on the viewer's canvas
        self.viewer.canvas.drop_target_register(DND_FILES)
        self.viewer.canvas.dnd_bind("<<Drop>>", self._on_drop)

        # ─── Dual-viewer container (used by color_correct tool) ─────────
        self.dual_viewer_frame = tk.Frame(self.main_frame)
        # Not packed by default — shown only when color correct tool is active

        self.cc_source_viewer = ImageViewer(self.dual_viewer_frame)
        self.cc_source_viewer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.cc_source_viewer.set_on_zoom_changed(self._on_zoom_changed)
        self.cc_source_viewer.set_on_draw_overlay(self._draw_cc_source_overlay)

        # Drag-and-drop on the source viewer for loading source image
        self.cc_source_viewer.canvas.drop_target_register(DND_FILES)
        self.cc_source_viewer.canvas.dnd_bind("<<Drop>>", self._on_cc_source_drop)

        # Separator between the two viewers
        sep = tk.Frame(self.dual_viewer_frame, width=2, bg="#888888")
        sep.pack(side=tk.LEFT, fill=tk.Y)

        self.cc_ref_viewer = ImageViewer(self.dual_viewer_frame)
        self.cc_ref_viewer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.cc_ref_viewer.set_on_draw_overlay(self._draw_cc_ref_overlay)

        # Drag-and-drop on the reference viewer for loading reference image
        self.cc_ref_viewer.canvas.drop_target_register(DND_FILES)
        self.cc_ref_viewer.canvas.dnd_bind("<<Drop>>", self._on_ref_drop)

        # ─── Side panel: BG removal (hidden by default) ─────────────────
        self.side_panel = tk.Frame(self.main_frame, width=280, bd=1, relief=tk.SUNKEN)
        self.bg_panel = BgRemovalPanel(
            self.side_panel,
            on_preview_ready=self._on_bg_preview_ready,
            on_apply=self._on_bg_apply,
            on_cancel=self._on_bg_cancel,
            on_status_changed=self._set_status,
        )

        # ─── Side panel: Color correction (hidden by default) ───────────
        self.cc_side_panel = tk.Frame(self.main_frame, width=280, bd=1, relief=tk.SUNKEN)
        self.cc_panel = ColorCorrectionPanel(
            self.cc_side_panel,
            on_preview_ready=self._on_cc_preview_ready,
            on_apply=self._on_cc_apply,
            on_cancel=self._on_cc_cancel,
            on_status_changed=self._set_status,
        )

        # ─── Side panel: Sprite crop (hidden by default) ────────────────
        self.crop_side_panel = tk.Frame(self.main_frame, width=280, bd=1, relief=tk.SUNKEN)
        self.crop_panel = SpriteCropPanel(
            self.crop_side_panel,
            on_apply=self._on_crop_apply,
            on_cancel=self._on_crop_cancel,
            on_overlay_changed=self._on_crop_overlay_changed,
        )

    def _build_status_bar(self):
        self.status_bar = tk.Frame(self.root, bd=1, relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_text = tk.Label(
            self.status_bar, text="Ready", anchor=tk.W, padx=8, font=("", 9)
        )
        self.status_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _set_status(self, text):
        """Update the status bar text."""
        self.status_text.config(text=text)

    # ─── Event Bindings ─────────────────────────────────────────────────

    def _bind_events(self):
        self.root.bind("<Control-o>", lambda e: self.open_image())
        self.root.bind("<Control-s>", lambda e: self.save_image())
        self.root.bind("<Control-q>", lambda e: self.root.quit())

    # ─── Tool Selection ─────────────────────────────────────────────────

    def _select_cursor_tool(self):
        self.active_tool = self.TOOL_CURSOR
        self.cursor_btn.config(relief=tk.SUNKEN)
        self.bg_remove_btn.config(relief=tk.RAISED)
        self.cc_btn.config(relief=tk.RAISED)
        self.crop_btn.config(relief=tk.RAISED)
        self._hide_all_panels()
        self._show_single_viewer()
        self.preview_image = None
        # In cursor mode, left-click pans
        self.viewer.set_left_click_pans(True)
        self.viewer.set_on_left_click(None)
        self._update_viewer_image()

    def _select_bg_remove_tool(self):
        if self.original_image is None:
            messagebox.showinfo("Info", "Open an image first.")
            return
        self.active_tool = self.TOOL_BG_REMOVE
        self.cursor_btn.config(relief=tk.RAISED)
        self.bg_remove_btn.config(relief=tk.SUNKEN)
        self.cc_btn.config(relief=tk.RAISED)
        self.crop_btn.config(relief=tk.RAISED)
        self._hide_all_panels()
        self._show_single_viewer()
        self.preview_image = None
        self.bg_panel.reset()
        self.bg_panel.set_source_image(self.original_image)
        self.side_panel.pack(side=tk.RIGHT, fill=tk.Y)
        # In BG remove mode, left-click adds points
        self.viewer.set_left_click_pans(False)
        self.viewer.set_on_left_click(self._bg_add_point)
        self._update_viewer_image()

    def _select_color_correct_tool(self):
        if self.original_image is None:
            messagebox.showinfo("Info", "Open an image first.")
            return
        self.active_tool = self.TOOL_COLOR_CORRECT
        self.cursor_btn.config(relief=tk.RAISED)
        self.bg_remove_btn.config(relief=tk.RAISED)
        self.cc_btn.config(relief=tk.SUNKEN)
        self.crop_btn.config(relief=tk.RAISED)
        self._hide_all_panels()
        self._show_dual_viewer()
        self.preview_image = None
        self.cc_panel.reset()
        self.cc_panel.set_source_image(self.original_image)
        if self.reference_image is not None:
            self.cc_panel.set_reference_image(self.reference_image)
        self.cc_side_panel.pack(side=tk.RIGHT, fill=tk.Y)
        # Source viewer: left-click picks source point
        self.cc_source_viewer.set_left_click_pans(False)
        self.cc_source_viewer.set_on_left_click(self._cc_source_click)
        # Reference viewer: left-click picks ref point or loads image
        self.cc_ref_viewer.set_left_click_pans(False)
        self.cc_ref_viewer.set_on_left_click(self._cc_ref_click)
        # Update viewers
        self.cc_source_viewer.image = self.original_image
        self.cc_source_viewer.fit_image()
        self.cc_ref_viewer.image = self.reference_image
        if self.reference_image:
            self.cc_ref_viewer.fit_image()

    def _show_single_viewer(self):
        """Show the single viewer, hide dual viewer."""
        self.dual_viewer_frame.pack_forget()
        self.single_viewer_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _show_dual_viewer(self):
        """Show the dual viewer, hide single viewer."""
        self.single_viewer_frame.pack_forget()
        self.dual_viewer_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _hide_all_panels(self):
        self.side_panel.pack_forget()
        self.cc_side_panel.pack_forget()
        self.crop_side_panel.pack_forget()

    # ─── Background Removal Callbacks ───────────────────────────────────

    def _on_bg_preview_ready(self, image):
        """Called from BgRemovalPanel when preview is computed."""
        self.preview_image = image
        self._update_viewer_image()

    def _on_bg_apply(self, image):
        """Called when user applies the background removal."""
        self.original_image = image.copy()
        self.preview_image = None
        self.bg_panel.reset()
        self._select_cursor_tool()

    def _on_bg_cancel(self):
        """Called when user cancels background removal."""
        self.preview_image = None
        self.bg_panel.reset()
        self._select_cursor_tool()

    # ─── Color Correction Callbacks ─────────────────────────────────────

    def _on_cc_preview_ready(self, image):
        """Called from ColorCorrectionPanel when preview is computed."""
        self.preview_image = image
        # Update the source viewer with the preview (or original if None)
        display = self.preview_image if self.preview_image else self.original_image
        self.cc_source_viewer.image = display

    def _on_cc_apply(self, image):
        """Called when user applies the color correction."""
        self.original_image = image.copy()
        self.preview_image = None
        self.cc_panel.reset()
        self._select_cursor_tool()

    def _on_cc_cancel(self):
        """Called when user cancels color correction."""
        self.preview_image = None
        self.cc_panel.reset()
        self._select_cursor_tool()

    def _cc_source_click(self, img_x, img_y, event):
        """Handle left-click on the source viewer in color correct mode."""
        self.cc_panel.on_source_click(img_x, img_y)
        self.cc_source_viewer.render()
        self.cc_ref_viewer.render()

    def _cc_ref_click(self, img_x, img_y, event):
        """Handle left-click on the reference viewer in color correct mode."""
        if self.reference_image is None:
            # No reference image loaded yet — prompt to load one
            self._load_reference_image()
            return
        self.cc_panel.on_reference_click(img_x, img_y)
        self.cc_ref_viewer.render()
        self.cc_source_viewer.render()

    # ─── Sprite Crop Tool ───────────────────────────────────────────────

    def _select_sprite_crop_tool(self):
        if self.original_image is None:
            messagebox.showinfo("Info", "Open an image first.")
            return
        self.active_tool = self.TOOL_SPRITE_CROP
        self.cursor_btn.config(relief=tk.RAISED)
        self.bg_remove_btn.config(relief=tk.RAISED)
        self.cc_btn.config(relief=tk.RAISED)
        self.crop_btn.config(relief=tk.SUNKEN)
        self._hide_all_panels()
        self._show_single_viewer()
        self.preview_image = None
        self.crop_panel.reset()
        self.crop_panel.set_source_image(self.original_image)
        self.crop_side_panel.pack(side=tk.RIGHT, fill=tk.Y)
        # In sprite crop mode, left-click pans (no click interaction needed)
        self.viewer.set_left_click_pans(True)
        self.viewer.set_on_left_click(None)
        self._update_viewer_image()

    def _on_crop_apply(self, cropped_image):
        """Called when user applies the sprite crop."""
        self.original_image = cropped_image.copy()
        self.preview_image = None
        self.crop_panel.reset()
        self._select_cursor_tool()

    def _on_crop_cancel(self):
        """Called when user cancels sprite crop."""
        self.preview_image = None
        self.crop_panel.reset()
        self._select_cursor_tool()

    def _on_crop_overlay_changed(self):
        """Called when crop parameters change — re-render to update overlay."""
        self.viewer.render()

    # ─── Color Correction Overlays ──────────────────────────────────────

    def _draw_cc_source_overlay(self, canvas, draw_x, draw_y, zoom_level):
        """Draw source point markers on the source viewer."""
        if self.active_tool != self.TOOL_COLOR_CORRECT:
            return
        for i, pair in enumerate(self.cc_panel.pairs):
            px = draw_x + (pair["src_x"] + 0.5) * zoom_level
            py = draw_y + (pair["src_y"] + 0.5) * zoom_level
            r = 5
            canvas.create_oval(
                px - r, py - r, px + r, py + r,
                outline="cyan", width=2
            )
            canvas.create_text(
                px + r + 3, py, text=str(i + 1),
                fill="cyan", anchor=tk.W, font=("", 8)
            )

    def _draw_cc_ref_overlay(self, canvas, draw_x, draw_y, zoom_level):
        """Draw reference point markers on the reference viewer."""
        if self.active_tool != self.TOOL_COLOR_CORRECT:
            return
        if self.reference_image is None:
            # Draw hint text
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            canvas.create_text(
                cw / 2, ch / 2,
                text="Click or drag-and-drop\nto load reference image",
                fill="#aaaaaa", font=("", 12), justify=tk.CENTER
            )
            return
        for i, pair in enumerate(self.cc_panel.pairs):
            px = draw_x + (pair["ref_x"] + 0.5) * zoom_level
            py = draw_y + (pair["ref_y"] + 0.5) * zoom_level
            r = 5
            canvas.create_oval(
                px - r, py - r, px + r, py + r,
                outline="magenta", width=2
            )
            canvas.create_text(
                px + r + 3, py, text=str(i + 1),
                fill="magenta", anchor=tk.W, font=("", 8)
            )

    # ─── Viewer Callbacks (single viewer) ───────────────────────────────

    def _get_bg_color(self):
        """Return the background color for RGBA compositing, or None."""
        return self.bg_panel.get_preview_bg_color()

    def _on_zoom_changed(self, zoom_level):
        """Update the zoom label when the viewer zoom changes."""
        percent = int(zoom_level * 100)
        self.zoom_label.config(text=f"{percent}%")

    def _toggle_zoom(self):
        """Toggle between fit-to-canvas and 100% zoom on the active viewer(s)."""
        if self.active_tool == self.TOOL_COLOR_CORRECT:
            self.cc_source_viewer.reset_zoom()
            if self.reference_image is not None:
                self.cc_ref_viewer.reset_zoom()
        else:
            self.viewer.reset_zoom()

    def _draw_overlay(self, canvas, draw_x, draw_y, zoom_level):
        """Draw point markers when in BG remove mode, or grid when in sprite crop mode."""
        if self.active_tool == self.TOOL_BG_REMOVE:
            for i, pt in enumerate(self.bg_panel.points):
                px = draw_x + (pt["x"] + 0.5) * zoom_level
                py = draw_y + (pt["y"] + 0.5) * zoom_level
                r = 5
                canvas.create_oval(
                    px - r, py - r, px + r, py + r,
                    outline="red", width=2
                )
                canvas.create_text(
                    px + r + 3, py, text=str(i + 1),
                    fill="red", anchor=tk.W, font=("", 8)
                )
        elif self.active_tool == self.TOOL_SPRITE_CROP:
            self.crop_panel.draw_overlay(canvas, draw_x, draw_y, zoom_level)

    def _bg_add_point(self, img_x, img_y, event):
        """Handle left-click in BG remove mode to add a sample point."""
        self.bg_panel.add_point(img_x, img_y)

    # ─── Image Management ───────────────────────────────────────────────

    def _update_viewer_image(self):
        """Update the single viewer with the current display image."""
        display = self.preview_image if self.preview_image else self.original_image
        self.viewer.image = display

    # ─── Reference Image Loading ────────────────────────────────────────

    def _load_reference_image(self):
        """Open a file dialog to load the reference image."""
        path = filedialog.askopenfilename(
            title="Open Reference Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._set_reference_image(path)

    def _set_reference_image(self, path):
        """Load a reference image from path."""
        try:
            self.reference_image = Image.open(path)
            self.reference_image.load()
        except Exception as e:
            messagebox.showerror("Error", f"Could not open reference image:\n{e}")
            return
        self.cc_panel.set_reference_image(self.reference_image)
        self.cc_ref_viewer.image = self.reference_image
        self.cc_ref_viewer.fit_image()

    def _on_ref_drop(self, event):
        """Handle drag-and-drop on the reference viewer."""
        path = event.data.strip()
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        self._set_reference_image(path)

    def _on_cc_source_drop(self, event):
        """Handle drag-and-drop on the source viewer in color correct mode."""
        path = event.data.strip()
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        self._load_image(path)
        # Update the color correction tool state with the new source
        if self.original_image is not None and self.active_tool == self.TOOL_COLOR_CORRECT:
            self.cc_panel.reset()
            self.cc_panel.set_source_image(self.original_image)
            if self.reference_image is not None:
                self.cc_panel.set_reference_image(self.reference_image)
            self.cc_source_viewer.image = self.original_image
            self.cc_source_viewer.fit_image()

    # ─── Drag and Drop (main viewer) ───────────────────────────────────

    def _on_drop(self, event):
        path = event.data.strip()
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        self._load_image(path)

    # ─── File Operations ────────────────────────────────────────────────

    def open_image(self):
        path = filedialog.askopenfilename(
            title="Open Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._load_image(path)

    def _load_image(self, path):
        try:
            self.original_image = Image.open(path)
            self.original_image.load()
        except Exception as e:
            messagebox.showerror("Error", f"Could not open image:\n{e}")
            return

        self.preview_image = None
        self.viewer.image = self.original_image
        self.viewer.fit_image()
        self.root.title(f"Image Editor — {path}")

    def save_image(self):
        if self.original_image is None:
            messagebox.showinfo("Save", "No image to save.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Image As",
            defaultextension=".png",
            filetypes=[
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("BMP", "*.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            self.original_image.save(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save image:\n{e}")


def main():
    root = TkinterDnD.Tk()
    ImageEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
