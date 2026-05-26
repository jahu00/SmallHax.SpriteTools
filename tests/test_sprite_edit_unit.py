"""Unit tests for SpriteEditPanel UI behavior.

Tests verify:
1. Section label text equals "Tile Edit"
2. Controls disabled when no import exists for selected tile
3. Controls enabled when import is assigned
4. Scaling method dropdown has exactly 6 options, defaults to "Lanczos"
5. File dialog opens on canvas click (mocked)
6. Cancel dialog makes no state change
"""

import sys
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image
from tkinterdnd2 import TkinterDnD

sys.path.insert(0, "/home/jahu/image-edit")

from se_panel import SpriteEditPanel, TileImportState, RESAMPLE_METHODS


@pytest.fixture
def panel():
    """Create a SpriteEditPanel instance with a real Tk root for testing."""
    root = TkinterDnD.Tk()
    root.withdraw()  # Hide the window

    frame = tk.Frame(root)
    frame.pack()

    on_apply = MagicMock()
    on_cancel = MagicMock()

    p = SpriteEditPanel(frame, on_apply, on_cancel)

    yield p

    root.destroy()


@pytest.fixture
def panel_with_image(panel):
    """Panel with a source image set (64x64 RGBA, 2x2 grid)."""
    img = Image.new("RGBA", (64, 64), (100, 150, 200, 255))
    panel.set_source_image(img)
    return panel


class TestSectionLabel:
    """Validates: Requirement 1.1"""

    def test_section_label_text_equals_tile_edit(self, panel):
        """The section header for tile editing should read 'Tile Edit'."""
        # Walk through all children of the parent frame to find the label
        found = False
        for widget in panel.parent_frame.winfo_children():
            if isinstance(widget, tk.Label):
                text = widget.cget("text")
                if text == "Tile Edit:":
                    found = True
                    break
        assert found, "Expected a label with text 'Tile Edit:' in the panel"


class TestControlsDisabledWithoutImport:
    """Validates: Requirements 5.5, 6.3, 7.3, 8.4"""

    def test_margin_controls_disabled_no_import(self, panel_with_image):
        """Margin/crop spinboxes should be disabled when no import exists."""
        p = panel_with_image
        assert str(p._margin_top_spin.cget("state")) == "disabled"
        assert str(p._margin_bottom_spin.cget("state")) == "disabled"
        assert str(p._margin_left_spin.cget("state")) == "disabled"
        assert str(p._margin_right_spin.cget("state")) == "disabled"

    def test_offset_controls_disabled_no_import(self, panel_with_image):
        """Offset spinboxes should be disabled when no import exists."""
        p = panel_with_image
        assert str(p._offset_x_spin.cget("state")) == "disabled"
        assert str(p._offset_y_spin.cget("state")) == "disabled"

    def test_tweak_scale_disabled_no_import(self, panel_with_image):
        """Tweak scale spinbox should be disabled when no import exists."""
        p = panel_with_image
        assert str(p._tweak_scale_spin.cget("state")) == "disabled"

    def test_scaling_method_disabled_no_import(self, panel_with_image):
        """Scaling method combobox should be disabled when no import exists."""
        p = panel_with_image
        assert str(p._scaling_method_combo.cget("state")) == "disabled"


class TestControlsEnabledWithImport:
    """Validates: Requirements 5.5, 6.3, 7.3, 8.1, 8.2"""

    def _assign_import(self, panel):
        """Helper to assign an import to the current tile."""
        img = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
        current_index = panel._tile_index_var.get()
        panel._tile_imports[current_index] = TileImportState(source_image=img)
        panel._sync_import_controls()

    def test_margin_controls_enabled_with_import(self, panel_with_image):
        """Margin/crop spinboxes should be enabled when import is assigned."""
        p = panel_with_image
        self._assign_import(p)
        assert str(p._margin_top_spin.cget("state")) == "normal"
        assert str(p._margin_bottom_spin.cget("state")) == "normal"
        assert str(p._margin_left_spin.cget("state")) == "normal"
        assert str(p._margin_right_spin.cget("state")) == "normal"

    def test_offset_controls_enabled_with_import(self, panel_with_image):
        """Offset spinboxes should be enabled when import is assigned."""
        p = panel_with_image
        self._assign_import(p)
        assert str(p._offset_x_spin.cget("state")) == "normal"
        assert str(p._offset_y_spin.cget("state")) == "normal"

    def test_tweak_scale_enabled_with_import(self, panel_with_image):
        """Tweak scale spinbox should be enabled when import is assigned."""
        p = panel_with_image
        self._assign_import(p)
        assert str(p._tweak_scale_spin.cget("state")) == "normal"

    def test_scaling_method_enabled_with_import(self, panel_with_image):
        """Scaling method combobox should be 'readonly' (enabled) when import is assigned."""
        p = panel_with_image
        self._assign_import(p)
        assert str(p._scaling_method_combo.cget("state")) == "readonly"


class TestScalingMethodDropdown:
    """Validates: Requirements 8.1, 8.2"""

    def test_scaling_method_has_six_options(self, panel):
        """Scaling method dropdown should have exactly 6 options."""
        values = list(panel._scaling_method_combo.cget("values"))
        assert len(values) == 6

    def test_scaling_method_options_correct(self, panel):
        """Scaling method dropdown options should be Nearest, Bilinear, Bicubic, Lanczos, Box, Hamming."""
        values = list(panel._scaling_method_combo.cget("values"))
        expected = ["Nearest", "Bilinear", "Bicubic", "Lanczos", "Box", "Hamming"]
        assert values == expected

    def test_scaling_method_defaults_to_lanczos(self, panel):
        """Scaling method should default to 'Lanczos'."""
        assert panel._scaling_method_var.get() == "Lanczos"


class TestFileDialogOnCanvasClick:
    """Validates: Requirements 3.1, 3.5"""

    @patch("se_panel.filedialog.askopenfilename")
    def test_file_dialog_opens_on_canvas_click(self, mock_dialog, panel_with_image):
        """Clicking the canvas should open a file dialog."""
        mock_dialog.return_value = ""  # Simulate cancel
        p = panel_with_image

        # Simulate a click event on the canvas
        event = MagicMock()
        event.x = 100
        event.y = 100
        p._on_canvas_click(event)

        mock_dialog.assert_called_once()

    @patch("se_panel.filedialog.askopenfilename")
    def test_cancel_dialog_no_state_change(self, mock_dialog, panel_with_image):
        """Cancelling the file dialog should make no state change."""
        mock_dialog.return_value = ""  # Empty string = cancel
        p = panel_with_image

        # Record state before
        imports_before = dict(p._tile_imports)
        margin_top_before = p._margin_top_var.get()
        offset_x_before = p._offset_x_var.get()
        tweak_scale_before = p._tweak_scale_var.get()
        scaling_method_before = p._scaling_method_var.get()

        # Simulate click
        event = MagicMock()
        event.x = 100
        event.y = 100
        p._on_canvas_click(event)

        # Verify no state change
        assert p._tile_imports == imports_before
        assert p._margin_top_var.get() == margin_top_before
        assert p._offset_x_var.get() == offset_x_before
        assert p._tweak_scale_var.get() == tweak_scale_before
        assert p._scaling_method_var.get() == scaling_method_before
