import tkinter as tk
from unittest.mock import Mock, patch
import pytest

from neko_launcher.ui.platform.window_chrome import (
    WindowDragHandler,
    _set_native_window_position,
)

@pytest.fixture
def tk_root():
    root = Mock(
        spec=[
            "after",
            "after_cancel",
            "geometry",
            "winfo_exists",
            "winfo_id",
            "winfo_x",
            "winfo_y",
        ]
    )
    root.winfo_exists.return_value = True
    return root

class TestWindowDragHandler:
    @patch("neko_launcher.ui.platform.window_chrome.sys.platform", "win32")
    def test_windows_drag_coalescing(self, tk_root):
        """Verify that on Windows, drag events are coalesced and use SetWindowPos."""
        handler = WindowDragHandler(tk_root)
        handler._is_win32 = True
        
        with patch.object(tk_root, "winfo_x", return_value=100), \
             patch.object(tk_root, "winfo_y", return_value=100):
             
             mock_start_event = Mock(spec=tk.Event)
             mock_start_event.x_root = 150
             mock_start_event.y_root = 150
             
             # offset should be 150 - 100 = 50
             handler.start(mock_start_event)
             assert handler._offset_x == 50
             assert handler._offset_y == 50
             
             with patch.object(tk_root, "after") as mock_after, \
                  patch.object(tk_root, "after_cancel") as mock_after_cancel, \
                  patch("neko_launcher.ui.platform.window_chrome._set_native_window_position") as mock_set_pos:
                  
                  mock_after.return_value = "job_id_123"
                  
                  # First drag event
                  mock_drag_event1 = Mock(spec=tk.Event)
                  mock_drag_event1.x_root = 200
                  mock_drag_event1.y_root = 200
                  handler.drag(mock_drag_event1)
                  
                  # Should have scheduled a move
                  mock_after.assert_called_once()
                  assert handler._pending_x == 150 # 200 - 50
                  assert handler._pending_y == 150 # 200 - 50
                  assert handler._move_job == "job_id_123"
                  
                  # Second drag event rapidly (before after timer fires)
                  mock_drag_event2 = Mock(spec=tk.Event)
                  mock_drag_event2.x_root = 300
                  mock_drag_event2.y_root = 300
                  handler.drag(mock_drag_event2)
                  
                  # Shouldn't schedule another job, just update pending coords
                  mock_after.assert_called_once()
                  assert handler._pending_x == 250
                  assert handler._pending_y == 250
                  
                  # Simulate mouse release (stop)
                  handler.stop(Mock(spec=tk.Event))
                  
                  # Should cancel pending job and flush synchronously
                  mock_after_cancel.assert_called_once_with("job_id_123")
                  mock_set_pos.assert_called_once_with(tk_root, 250, 250)
                  assert handler._move_job is None
                  assert handler._pending_x is None
                  assert handler._pending_y is None

    @patch("neko_launcher.ui.platform.window_chrome.sys.platform", "win32")
    def test_windows_flush_move(self, tk_root):
        """Verify _flush_move invokes _set_native_window_position."""
        handler = WindowDragHandler(tk_root)
        handler._is_win32 = True
        
        handler._pending_x = 500
        handler._pending_y = 600
        handler._move_job = "dummy_job"
        
        with patch("neko_launcher.ui.platform.window_chrome._set_native_window_position") as mock_set_pos:
            handler._flush_move()
            
            assert handler._move_job is None
            assert handler._pending_x is None
            assert handler._pending_y is None
            mock_set_pos.assert_called_once_with(tk_root, 500, 600)

    @patch("neko_launcher.ui.platform.window_chrome.sys.platform", "linux")
    def test_non_windows_fallback(self, tk_root):
        """Verify absolute offset geometry dragging is used on non-Windows."""
        handler = WindowDragHandler(tk_root)
        handler._is_win32 = False
        
        with patch.object(tk_root, "winfo_x", return_value=10), \
             patch.object(tk_root, "winfo_y", return_value=20):
             
             mock_start_event = Mock(spec=tk.Event)
             mock_start_event.x_root = 100
             mock_start_event.y_root = 100
             
             handler.start(mock_start_event)
             
             # offset_x = 100 - 10 = 90
             # offset_y = 100 - 20 = 80
             assert handler._offset_x == 90
             assert handler._offset_y == 80
             
             mock_drag_event = Mock(spec=tk.Event)
             mock_drag_event.x_root = 150
             mock_drag_event.y_root = 150
             
             with patch.object(tk_root, "geometry") as mock_geometry:
                 handler.drag(mock_drag_event)
                 
                 # x = 150 - 90 = 60
                 # y = 150 - 80 = 70
                 mock_geometry.assert_called_once_with("+60+70")

    @patch("neko_launcher.ui.platform.window_chrome.sys.platform", "win32")
    def test_windows_native_failure_is_graceful(self, tk_root):
        """Verify that if Win32 APIs fail, the launcher doesn't crash."""
        with patch("neko_launcher.ui.platform.window_chrome._get_window_handle", return_value=0):
            # Should safely return without crashing
            _set_native_window_position(tk_root, 100, 100)
            
        with patch("neko_launcher.ui.platform.window_chrome._get_window_handle", return_value=12345), \
             patch("ctypes.windll.user32.SetWindowPos", side_effect=Exception("API failure")):
            # Should safely catch exception without crashing
            _set_native_window_position(tk_root, 100, 100)
