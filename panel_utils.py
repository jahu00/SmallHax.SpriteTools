"""Reusable Tkinter helpers for the tool side panels.

Provides:

* ``bind_mousewheel_tree`` — recursively route mouse-wheel events over a
  widget subtree to a canvas, so scrolling works while hovering child
  widgets (labels, spinboxes, ...), not just the bare canvas. If the
  targeted canvas cannot scroll, the event bubbles up to the nearest
  scrollable ancestor canvas, giving natural nested-scroll behaviour.

* ``make_scrollable`` — wrap a fixed-size side-panel frame so the *whole*
  panel scrolls vertically. The scrollbar lives on the right edge and is
  only shown when the content is taller than the visible area.

* ``ReflowingList`` — a scrollable list of "card" widgets that lays cards
  out two-per-row when there is room and falls back to a single column
  when the panel is narrow. Its own scrollbar sits on the *left* so it
  never gets clipped/hidden at small panel widths.
"""

import tkinter as tk


def _scroll_canvas_or_ancestor(canvas, direction):
    """Scroll ``canvas`` if it has overflow, else walk up to one that does."""
    node = canvas
    while node is not None:
        if isinstance(node, tk.Canvas):
            first, last = node.yview()
            if not (first <= 0.0 and last >= 1.0):
                node.yview_scroll(direction, "units")
                return True
        node = node.master
    return False


def bind_mousewheel_tree(widget, canvas, claim=False):
    """Bind mouse-wheel scrolling for ``canvas`` across a widget subtree.

    Tk delivers wheel events to the widget under the pointer, so binding
    only the canvas means the wheel is dead while hovering the child
    widgets that sit on top of it. This walks the subtree and binds each
    widget to scroll ``canvas`` (or the nearest scrollable ancestor when
    ``canvas`` itself is fully visible).

    A subtree may be "locked" to a different canvas (e.g. an inner
    :class:`ReflowingList`). Locked subtrees are skipped unless ``claim``
    is True (used by the owner of that subtree).
    """
    if getattr(widget, "_wheel_locked", False) and not claim:
        return

    def _on_wheel(event, c=canvas):
        if event.num == 4:
            direction = -1
        elif event.num == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        _scroll_canvas_or_ancestor(c, direction)
        return "break"

    widget.bind("<Button-4>", _on_wheel)
    widget.bind("<Button-5>", _on_wheel)
    widget.bind("<MouseWheel>", _on_wheel)

    for child in widget.winfo_children():
        bind_mousewheel_tree(child, canvas, claim=claim)


def _make_autohide(canvas, scrollbar, inner, side, orient="vertical"):
    """Return a handler that shows/hides ``scrollbar`` based on fit.

    When ``inner`` is larger than the visible ``canvas`` area the
    scrollbar is packed (on ``side``); otherwise it is hidden. Also keeps
    the canvas scrollregion in sync.
    """

    def _update(_event=None):
        canvas.update_idletasks()
        if orient == "vertical":
            needed = inner.winfo_reqheight() > canvas.winfo_height()
        else:
            needed = inner.winfo_reqwidth() > canvas.winfo_width()

        if needed:
            if not scrollbar.winfo_ismapped():
                fill = tk.Y if orient == "vertical" else tk.X
                scrollbar.pack(side=side, fill=fill, before=canvas)
        else:
            if scrollbar.winfo_ismapped():
                scrollbar.pack_forget()

        canvas.configure(scrollregion=canvas.bbox("all"))

    return _update


def make_scrollable(outer_frame):
    """Make ``outer_frame`` host vertically-scrollable content.

    Returns the inner content frame; build the panel UI into it exactly
    as if it were the original frame. The vertical scrollbar sits on the
    right and auto-hides when everything fits.
    """
    # Keep the panel at its configured (fixed) size instead of shrinking
    # to fit its children.
    outer_frame.pack_propagate(False)

    canvas = tk.Canvas(outer_frame, highlightthickness=0, bd=0)
    vscroll = tk.Scrollbar(outer_frame, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=vscroll.set)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    content = tk.Frame(canvas)
    window_id = canvas.create_window((0, 0), window=content, anchor=tk.NW)

    autohide = _make_autohide(canvas, vscroll, content, side=tk.RIGHT)

    def _fit_content_height():
        # When the content is shorter than the visible canvas, stretch it
        # to fill the panel so widgets using expand=True (e.g. the point
        # list) can grow. When it is taller, keep its natural height so it
        # scrolls instead.
        canvas.update_idletasks()
        avail = canvas.winfo_height()
        needed = content.winfo_reqheight()
        canvas.itemconfigure(window_id, height=max(avail, needed))

    def _on_canvas_configure(event):
        # Stretch the content to the canvas width so it fills the panel.
        canvas.itemconfigure(window_id, width=event.width)
        _fit_content_height()
        autohide()

    def _on_content_configure(_e):
        _fit_content_height()
        autohide()

    content.bind("<Configure>", _on_content_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    # Bind the wheel once the panel content has been populated.
    def _bind_wheel():
        bind_mousewheel_tree(content, canvas)
        autohide()

    canvas.after_idle(_bind_wheel)

    # Expose the canvas so callers can re-bind the wheel after building.
    content._scroll_canvas = canvas
    return content


class ReflowingList:
    """Scrollable, wrapping list of fixed-size card widgets.

    Cards are created via :meth:`new_card` (do not pack/grid them
    yourself) and laid out by :meth:`reflow`. As many cards as fit are
    packed per row at their natural width; the rest wrap to the next
    row. Cards are never stretched or shrunk — when the panel is too
    narrow for even one full card, a single column is used and the
    horizontal scrolling is avoided by letting the card keep its size.

    The scrollbar is on the left so it stays visible at any width.
    """

    _PAD = 2  # padding around each card (matches grid padx/pady)

    def __init__(self, parent, height=150):
        self._cards = []
        self._card_width = 1
        self._cols = 0

        self.frame = tk.Frame(parent)
        # Mark the subtree so an outer make_scrollable() wheel binding
        # leaves this list alone; the list owns its own wheel routing.
        self.frame._wheel_locked = True

        self.canvas = tk.Canvas(self.frame, highlightthickness=0, bd=0, height=height)
        self.scrollbar = tk.Scrollbar(self.frame, orient=tk.VERTICAL,
                                      command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.inner = tk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner,
                                                    anchor=tk.NW)

        self._autohide = _make_autohide(self.canvas, self.scrollbar, self.inner,
                                        side=tk.LEFT)

        self.inner.bind("<Configure>", lambda e: self._autohide())
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window_id, width=event.width)
        self._relayout_for_width(event.width)
        self._autohide()

    def clear(self):
        """Destroy all existing cards."""
        for card in self._cards:
            card.destroy()
        self._cards = []
        self._cols = 0

    def new_card(self, **kwargs):
        """Create and track a new card frame (not yet placed)."""
        card = tk.Frame(self.inner, **kwargs)
        self._cards.append(card)
        return card

    def reflow(self):
        """Lay out all cards for the current width and rebind the wheel."""
        width = self.canvas.winfo_width()
        if width <= 1:
            # Not realized yet; defer until we have a real size.
            self.canvas.after_idle(self.reflow)
            return
        self._measure_card_width()
        self._cols = 0  # force a fresh layout
        self._relayout_for_width(width)
        # Cards were recreated; route their wheel events to this canvas.
        bind_mousewheel_tree(self.frame, self.canvas, claim=True)
        self._autohide()

    def _measure_card_width(self):
        """Record the natural width of the widest card."""
        if not self._cards:
            return
        self.inner.update_idletasks()
        req = max(c.winfo_reqwidth() for c in self._cards)
        if req > 1:
            self._card_width = req

    def _columns_for_width(self, width):
        """How many natural-width cards fit across ``width`` (at least 1)."""
        slot = self._card_width + 2 * self._PAD
        if slot <= 0:
            return 1
        return max(1, width // slot)

    def _relayout_for_width(self, width):
        cols = self._columns_for_width(width)
        if cols != self._cols and self._cards:
            self._layout(cols)

    def _layout(self, cols):
        self._cols = cols
        for i, card in enumerate(self._cards):
            # sticky="nw" keeps each card at its natural size (no stretch,
            # no shrink) instead of filling the grid cell.
            card.grid_configure(row=i // cols, column=i % cols,
                                sticky="nw", padx=self._PAD, pady=self._PAD)
        # Remove weight from every column so cards are not stretched; only
        # the trailing empty space absorbs slack.
        max_cols = max(cols, self._grid_column_count())
        for c in range(max_cols):
            self.inner.grid_columnconfigure(c, weight=0, uniform="")
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _grid_column_count(self):
        """Highest configured grid column index + 1 (for cleanup)."""
        try:
            return int(self.inner.grid_size()[0])
        except Exception:
            return 0
