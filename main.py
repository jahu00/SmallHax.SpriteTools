#!/usr/bin/env python3
"""Simple image editor using Tkinter and Pillow."""

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image, ImageTk
import math

from bg_panel import BgRemovalPanel


# ─── Checkerboard Pattern ───────────────────────────────────────────────────

_checker_tile = None
_checker_tile_size = 8


def get_checker_tile(square_size=8):
    """Get or create a cached checkerboard tile."""
    global _checker_tile, _checker_tile_size
    if _checker_tile is None or _checker_tile_size != square_size:
        _checker_tile_size = square_size
        tile_size = square_size * 2
        tile = Image.new("RGB", (tile_size, tile_size))
        pixels = tile.load()
        for y in range(tile_size):
            for x in range(tile_size):
                if (x // square_size + y // square_size) % 2 == 0:
                    pixels[x, y] = (200, 200, 200)
                else:
                    pixels[x, y] = (255, 255, 255)
        _checker_tile = tile
    return _checker_tile


def create_checkerboard(width, height, square_size=8):
    """Create a checkerboard pattern image by tiling a small pattern."""
    tile = get_checker_tile(square_size)
    tile_w, tile_h = tile.size
    img = Image.new("RGB", (width, height))
    for y in range(0, height, tile_h):
        for x in range(0, width, tile_w):
            img.paste(tile, (x, y))
    return img


# ─── Main Application ──────────────────────────────────────────────────────

class ImageEditor:
    """Main application class for the image editor."""

    TOOL_CURSOR = "cursor"
    TOOL_BG_REMOVE = "bg_remove"

    def __init__(self, root):
        self.root = root
        self.root.title("Image Editor")
        self.root.geometry("1024x768")

        # Image state
        self.original_image = None
        self.preview_image = None
        self.zoom_level = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.tk_image = None

        # Pan state
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._pan_start_offset_x = 0
        self._pan_start_offset_y = 0

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

        # Zoom indicator label (click to toggle 100% / fit)
        self.zoom_label = tk.Label(toolbar, text="100%", padx=8, cursor="hand2")
        self.zoom_label.pack(side=tk.RIGHT, padx=4, pady=2)
        self.zoom_label.bind("<Button-1>", lambda e: self._reset_zoom())

    def _build_main_area(self):
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Canvas
        self.canvas_frame = tk.Frame(self.main_frame)
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#3c3c3c", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Side panel (hidden by default)
        self.side_panel = tk.Frame(self.main_frame, width=280, bd=1, relief=tk.SUNKEN)
        self.bg_panel = BgRemovalPanel(
            self.side_panel,
            on_preview_ready=self._on_bg_preview_ready,
            on_apply=self._on_bg_apply,
            on_cancel=self._on_bg_cancel,
            on_status_changed=self._set_status,
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

        # Zoom (Ctrl + scroll) — always
        self.canvas.bind("<Control-Button-4>", self._zoom_in)
        self.canvas.bind("<Control-Button-5>", self._zoom_out)

        # Middle mouse pan — always
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_motion)

        # Left click — tool-dependent
        self.canvas.bind("<ButtonPress-1>", self._on_left_click)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)

        # Redraw on resize
        self.canvas.bind("<Configure>", lambda e: self._render())

        # Drag-and-drop
        self.canvas.drop_target_register(DND_FILES)
        self.canvas.dnd_bind("<<Drop>>", self._on_drop)

    # ─── Tool Selection ─────────────────────────────────────────────────

    def _select_cursor_tool(self):
        self.active_tool = self.TOOL_CURSOR
        self.cursor_btn.config(relief=tk.SUNKEN)
        self.bg_remove_btn.config(relief=tk.RAISED)
        self._hide_side_panel()
        self.preview_image = None
        self._render()

    def _select_bg_remove_tool(self):
        if self.original_image is None:
            messagebox.showinfo("Info", "Open an image first.")
            return
        self.active_tool = self.TOOL_BG_REMOVE
        self.cursor_btn.config(relief=tk.RAISED)
        self.bg_remove_btn.config(relief=tk.SUNKEN)
        self.preview_image = None
        self.bg_panel.reset()
        self.bg_panel.set_source_image(self.original_image)
        self._show_side_panel()
        self._render()

    def _show_side_panel(self):
        self.side_panel.pack(side=tk.RIGHT, fill=tk.Y)

    def _hide_side_panel(self):
        self.side_panel.pack_forget()

    # ─── Background Removal Callbacks ───────────────────────────────────

    def _on_bg_preview_ready(self, image):
        """Called from BgRemovalPanel when preview is computed."""
        self.preview_image = image
        self._render()

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

    # ─── Left Click / Drag ──────────────────────────────────────────────

    def _on_left_click(self, event):
        if self.active_tool == self.TOOL_CURSOR:
            self._cursor_drag_start(event)
        elif self.active_tool == self.TOOL_BG_REMOVE:
            self._bg_add_point(event)

    def _on_left_drag(self, event):
        if self.active_tool == self.TOOL_CURSOR:
            self._cursor_drag_motion(event)

    # ─── Cursor Tool ────────────────────────────────────────────────────

    def _cursor_drag_start(self, event):
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._pan_start_offset_x = self.offset_x
        self._pan_start_offset_y = self.offset_y

    def _cursor_drag_motion(self, event):
        if self.original_image is None:
            return
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y
        self.offset_x = self._pan_start_offset_x + dx
        self.offset_y = self._pan_start_offset_y + dy
        self._render()

    # ─── Middle Mouse Pan ───────────────────────────────────────────────

    def _on_pan_start(self, event):
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._pan_start_offset_x = self.offset_x
        self._pan_start_offset_y = self.offset_y

    def _on_pan_motion(self, event):
        if self.original_image is None:
            return
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y
        self.offset_x = self._pan_start_offset_x + dx
        self.offset_y = self._pan_start_offset_y + dy
        self._render()

    # ─── Background Removal Point Adding ────────────────────────────────

    def _bg_add_point(self, event):
        if self.original_image is None:
            return

        draw_x = self._get_draw_offset_x()
        draw_y = self._get_draw_offset_y()

        img_x = int((event.x - draw_x) / self.zoom_level)
        img_y = int((event.y - draw_y) / self.zoom_level)

        w, h = self.original_image.size
        if img_x < 0 or img_x >= w or img_y < 0 or img_y >= h:
            return

        self.bg_panel.add_point(img_x, img_y)

    # ─── Drag and Drop ──────────────────────────────────────────────────

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
        self.zoom_level = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self._fit_image_to_canvas()
        self._render()
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

    # ─── Zoom ──────────────────────────────────────────────────────────

    def _zoom_in(self, event):
        self._zoom(event, factor=1.15)

    def _zoom_out(self, event):
        self._zoom(event, factor=1 / 1.15)

    def _zoom(self, event, factor):
        if self.original_image is None:
            return

        old_zoom = self.zoom_level
        self.zoom_level *= factor
        self.zoom_level = max(0.05, min(self.zoom_level, 50.0))

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        img_x = (canvas_x - self._get_draw_offset_x(old_zoom)) / old_zoom
        img_y = (canvas_y - self._get_draw_offset_y(old_zoom)) / old_zoom

        new_draw_x = canvas_x - img_x * self.zoom_level
        new_draw_y = canvas_y - img_y * self.zoom_level

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        iw = self.original_image.width * self.zoom_level
        ih = self.original_image.height * self.zoom_level

        self.offset_x = new_draw_x - (cw - iw) / 2
        self.offset_y = new_draw_y - (ch - ih) / 2

        self._update_zoom_label()
        self._render()

    def _get_draw_offset_x(self, zoom=None):
        if zoom is None:
            zoom = self.zoom_level
        cw = self.canvas.winfo_width()
        iw = self.original_image.width * zoom
        return (cw - iw) / 2 + self.offset_x

    def _get_draw_offset_y(self, zoom=None):
        if zoom is None:
            zoom = self.zoom_level
        ch = self.canvas.winfo_height()
        ih = self.original_image.height * zoom
        return (ch - ih) / 2 + self.offset_y

    def _reset_zoom(self):
        if self.original_image is None:
            return
        if self.zoom_level == 1.0:
            self._fit_image_to_canvas()
        else:
            self.zoom_level = 1.0
            self.offset_x = 0
            self.offset_y = 0
            self._update_zoom_label()
        self._render()

    def _update_zoom_label(self):
        percent = int(self.zoom_level * 100)
        self.zoom_label.config(text=f"{percent}%")

    # ─── Rendering ──────────────────────────────────────────────────────

    def _fit_image_to_canvas(self):
        if self.original_image is None:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = 1024, 768

        iw, ih = self.original_image.size
        scale_x = cw / iw
        scale_y = ch / ih
        self.zoom_level = min(scale_x, scale_y, 1.0)
        self.offset_x = 0
        self.offset_y = 0
        self._update_zoom_label()

    def _render(self):
        """Render only the visible portion of the image onto the canvas."""
        self.canvas.delete("all")

        if self.original_image is None:
            return

        display_image = self.preview_image if self.preview_image else self.original_image

        iw, ih = display_image.size
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        if cw <= 1 or ch <= 1:
            return

        draw_x = self._get_draw_offset_x()
        draw_y = self._get_draw_offset_y()

        # Visible region intersection
        img_canvas_right = draw_x + iw * self.zoom_level
        img_canvas_bottom = draw_y + ih * self.zoom_level

        crop_canvas_left = max(0, draw_x)
        crop_canvas_top = max(0, draw_y)
        crop_canvas_right = min(cw, img_canvas_right)
        crop_canvas_bottom = min(ch, img_canvas_bottom)

        if crop_canvas_left >= crop_canvas_right or crop_canvas_top >= crop_canvas_bottom:
            return

        # Convert to source image coordinates
        src_left = max(0, int((crop_canvas_left - draw_x) / self.zoom_level))
        src_top = max(0, int((crop_canvas_top - draw_y) / self.zoom_level))
        src_right = min(iw, int(math.ceil((crop_canvas_right - draw_x) / self.zoom_level)))
        src_bottom = min(ih, int(math.ceil((crop_canvas_bottom - draw_y) / self.zoom_level)))

        if src_right <= src_left or src_bottom <= src_top:
            return

        cropped = display_image.crop((src_left, src_top, src_right, src_bottom))

        out_w = max(1, int((src_right - src_left) * self.zoom_level))
        out_h = max(1, int((src_bottom - src_top) * self.zoom_level))

        resample = Image.LANCZOS if self.zoom_level < 1.0 else Image.NEAREST
        resized = cropped.resize((out_w, out_h), resample)

        # Composite RGBA over checkerboard or solid background
        if resized.mode == "RGBA":
            bg_color = self.bg_panel.get_preview_bg_color()
            if bg_color is not None:
                bg = Image.new("RGB", (out_w, out_h), bg_color)
            else:
                bg = create_checkerboard(out_w, out_h)
            bg.paste(resized, mask=resized.split()[3])
            resized = bg

        self.tk_image = ImageTk.PhotoImage(resized)

        place_x = draw_x + src_left * self.zoom_level
        place_y = draw_y + src_top * self.zoom_level
        self.canvas.create_image(place_x, place_y, anchor=tk.NW, image=self.tk_image)

        # Draw point markers
        if self.active_tool == self.TOOL_BG_REMOVE:
            for i, pt in enumerate(self.bg_panel.points):
                px = draw_x + pt["x"] * self.zoom_level
                py = draw_y + pt["y"] * self.zoom_level
                r = 5
                self.canvas.create_oval(
                    px - r, py - r, px + r, py + r,
                    outline="red", width=2
                )
                self.canvas.create_text(
                    px + r + 3, py, text=str(i + 1),
                    fill="red", anchor=tk.W, font=("", 8)
                )


def main():
    root = TkinterDnD.Tk()
    ImageEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
