import tkinter as tk
from unittest.mock import Mock, patch
import pytest

from neko_launcher.ui.platform.window_chrome import (
    WindowDragHandler,
    _pack_screen_point,
)

@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()

def test_pack_screen_point():
    """Verify negative and positive coordinates are correctly packed into LPARAM."""
    # Positive coordinates
    assert _pack_screen_point(100, 50) == 0x00320064
    
    # Negative X
    assert _pack_screen_point(-100, 50) == 0x0032FF9C
    
    # Negative Y
    assert _pack_screen_point(100, -50) == 0xFFCE0064
    
    # Negative X and Y (e.g. multi-monitor negative coordinate layout)
    assert _pack_screen_point(-1920, -100) == 0xFF9CF880

class TestWindowDragHandler:
    @patch("neko_launcher.ui.platform.window_chrome.sys.platform", "win32")
    def test_windows_start_schedules_drag_and_checks_mouse(self, tk_root):
        """
        Verify that on Windows, start() defers execution via after_idle
        and checks if the mouse button is still pressed before executing.
        """
        handler = WindowDragHandler(tk_root)
        
        # Override is_win32 flag which was set during __init__
        handler._is_win32 = True 
        
        mock_event = Mock(spec=tk.Event)
        mock_event.x_root = -1920
        mock_event.y_root = 100
        
        with patch.object(tk_root, "after_idle") as mock_after_idle:
            handler.start(mock_event)
            
            # 1. Ensure after_idle is called instead of synchronous execution
            mock_after_idle.assert_called_once()
            
            # Extract the scheduled callback
            callback = mock_after_idle.call_args[0][0]
            
            # Simulate invoking the callback
            with patch("neko_launcher.ui.platform.window_chrome._get_window_handle") as mock_get_hwnd, \
                 patch("ctypes.windll.user32.GetAsyncKeyState") as mock_get_async_key_state, \
                 patch("ctypes.windll.user32.ReleaseCapture") as mock_release_capture, \
                 patch("ctypes.windll.user32.SendMessageW") as mock_send_message:
                 
                 mock_get_hwnd.return_value = 12345
                 
                 # 2. Simulate mouse button RELEASED (state bit 0x8000 is 0)
                 mock_get_async_key_state.return_value = 0
                 callback()
                 
                 mock_get_async_key_state.assert_called_once_with(0x01) # VK_LBUTTON
                 mock_release_capture.assert_not_called()
                 mock_send_message.assert_not_called()
                 
                 mock_get_async_key_state.reset_mock()
                 
                 # 3. Simulate mouse button STILL PRESSED (state bit 0x8000 is 1)
                 mock_get_async_key_state.return_value = 0x8000
                 callback()
                 
                 mock_get_async_key_state.assert_called_once_with(0x01)
                 mock_release_capture.assert_called_once()
                 mock_send_message.assert_called_once()
                 
                 # Verify SendMessageW arguments
                 hwnd, msg, wparam, lparam = mock_send_message.call_args[0]
                 assert hwnd == 12345
                 assert msg == 0x00A1 # WM_NCLBUTTONDOWN
                 assert wparam == 2   # HTCAPTION
                 # Verify packed coordinate -1920, 100
                 assert lparam == _pack_screen_point(-1920, 100)

    @patch("neko_launcher.ui.platform.window_chrome.sys.platform", "win32")
    def test_windows_drag_is_noop(self, tk_root):
        """Verify that B1-Motion geometry fallback is disabled on Windows."""
        handler = WindowDragHandler(tk_root)
        handler._is_win32 = True
        
        with patch.object(tk_root, "geometry") as mock_geometry:
            handler.drag(Mock(spec=tk.Event))
            mock_geometry.assert_not_called()

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
        handler = WindowDragHandler(tk_root)
        handler._is_win32 = True
        
        # Override _get_window_handle to simulate failure
        with patch("neko_launcher.ui.platform.window_chrome._get_window_handle", return_value=0):
            # Should safely return without crashing
            handler._begin_native_drag(100, 100)
            
        with patch("neko_launcher.ui.platform.window_chrome._get_window_handle", return_value=12345), \
             patch("ctypes.windll.user32.GetAsyncKeyState", side_effect=Exception("API failure")):
            # Should safely catch exception without crashing
            handler._begin_native_drag(100, 100)
