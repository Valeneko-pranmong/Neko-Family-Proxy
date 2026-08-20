from typing import Any
import customtkinter as ctk
from neko_launcher.ui.platform.window_scaling import (
    calculate_portrait_geometry,
    calculate_centered_position,
    fit_portrait_window,
    center_window,
    DESIGN_WIDTH,
    DESIGN_HEIGHT,
    SCREEN_MARGIN_RATIO,
    SETTINGS_CONTENT_MIN_WIDTH,
    SETTINGS_FOOTER_RESERVE,
    SETTINGS_HEIGHT,
    SETTINGS_SIDEBAR_WIDTH,
    SETTINGS_WIDTH,
    calculate_settings_geometry,
)


class FakeSizingRoot:
    def __init__(self, screen_w: int = 1920, screen_h: int = 1080) -> None:
        self.events: list[str] = []
        self.minimum: tuple[int, int] | None = None
        self.maximum: tuple[int, int] | None = None
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.scaling = 1.0

    def update_idletasks(self) -> None:
        self.events.append("update_idletasks")

    def winfo_screenwidth(self) -> int:
        return self.screen_w

    def winfo_screenheight(self) -> int:
        return self.screen_h

    def winfo_exists(self) -> bool:
        return True

    def minsize(self, width: int, height: int) -> None:
        self.minimum = (width, height)
        self.events.append(f"minsize:{width}x{height}")

    def maxsize(self, width: int, height: int) -> None:
        self.maximum = (width, height)
        self.events.append(f"maxsize:{width}x{height}")

    def geometry(self, value: str) -> None:
        self.events.append(f"geometry:{value}")

    def winfo_width(self) -> int:
        return 440

    def winfo_height(self) -> int:
        return 580


def test_fit_portrait_window_pure_calculation() -> None:
    """Test the pure geometry calculation function directly."""
    geometry = calculate_portrait_geometry(
        screen_w=1920,
        screen_h=1080,
        window_scale=1.0,
        design_width=DESIGN_WIDTH,
        design_height=DESIGN_HEIGHT,
        margin_ratio=SCREEN_MARGIN_RATIO,
    )

    assert geometry.logical_width == 440
    assert geometry.logical_height == 592
    assert geometry.widget_scale == 1.0
    assert geometry.x == 740
    assert geometry.y == 244


def test_portrait_design_height_reserves_full_version_footer() -> None:
    assert DESIGN_HEIGHT == 592


def test_center_window_calculation() -> None:
    """Test the pure centering calculation function."""
    x, y = calculate_centered_position(1920, 1080, 440, 580)

    assert x == 740
    assert y == 250


def test_fit_portrait_window_adapter_100_percent_scaling(monkeypatch: Any) -> None:
    root = FakeSizingRoot(1920, 1080)
    set_scaling_calls: list[float] = []
    monkeypatch.setattr(ctk, "set_widget_scaling", lambda s: set_scaling_calls.append(s))
    monkeypatch.setattr(ctk.ScalingTracker, "get_window_scaling", lambda r: 1.0)

    fit_portrait_window(root)  # type: ignore[arg-type]

    assert "update_idletasks" in root.events
    assert "minsize:440x592" in root.events
    assert "maxsize:440x592" in root.events
    assert "geometry:440x592+740+244" in root.events
    assert set_scaling_calls == [1.0]


def test_fit_portrait_window_adapter_125_percent_scaling(monkeypatch: Any) -> None:
    # Simulating Windows 125% scaling (logical resolution drops by 1.25)
    # Physical 1920x1080 -> Logical 1536x864
    root = FakeSizingRoot(1536, 864)
    set_scaling_calls: list[float] = []
    monkeypatch.setattr(ctk, "set_widget_scaling", lambda s: set_scaling_calls.append(s))
    monkeypatch.setattr(ctk.ScalingTracker, "get_window_scaling", lambda r: 1.25)

    fit_portrait_window(root)  # type: ignore[arg-type]

    assert "minsize:352x473" in root.events
    assert set_scaling_calls == [0.8]


def test_fit_portrait_window_adapter_150_percent_scaling(monkeypatch: Any) -> None:
    # Simulating Windows 150% scaling
    # Physical 1920x1080 -> Logical 1280x720
    root = FakeSizingRoot(1280, 720)
    set_scaling_calls: list[float] = []
    monkeypatch.setattr(ctk, "set_widget_scaling", lambda s: set_scaling_calls.append(s))
    monkeypatch.setattr(ctk.ScalingTracker, "get_window_scaling", lambda r: 1.5)

    fit_portrait_window(root)  # type: ignore[arg-type]

    assert "minsize:293x394" in root.events


def test_fit_portrait_window_adapter_short_display(monkeypatch: Any) -> None:
    # 800x480 ultra-compact display at 100%
    root = FakeSizingRoot(800, 480)
    set_scaling_calls: list[float] = []
    monkeypatch.setattr(ctk, "set_widget_scaling", lambda s: set_scaling_calls.append(s))
    monkeypatch.setattr(ctk.ScalingTracker, "get_window_scaling", lambda r: 1.0)

    fit_portrait_window(root)  # type: ignore[arg-type]

    # Available height is 480 * 0.92 = 441.6 < 580, so scale down occurs
    assert set_scaling_calls[0] < 1.0


def test_center_window_adapter() -> None:
    root = FakeSizingRoot(1920, 1080)
    center_window(root, (440, 580))  # type: ignore[arg-type]
    
    assert "update_idletasks" in root.events
    assert "geometry:440x580+740+250" in root.events


def test_settings_layout_contract_preserves_content_and_footer_at_supported_dpi() -> None:
    for window_scale, screen_size in (
        (1.0, (1920, 1080)),
        (1.25, (1536, 864)),
        (1.5, (1280, 720)),
    ):
        geometry = calculate_settings_geometry(
            screen_w=screen_size[0],
            screen_h=screen_size[1],
            window_scale=window_scale,
        )

        assert geometry.logical_width == SETTINGS_WIDTH
        assert geometry.logical_height == SETTINGS_HEIGHT
        assert geometry.logical_width <= screen_size[0]
        assert geometry.logical_height + SETTINGS_FOOTER_RESERVE <= screen_size[1]
        assert geometry.logical_width - SETTINGS_SIDEBAR_WIDTH >= SETTINGS_CONTENT_MIN_WIDTH
        assert geometry.widget_scale == 1.0
