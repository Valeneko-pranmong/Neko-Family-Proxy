from __future__ import annotations

from pathlib import Path
import tkinter as tk
import pytest
import customtkinter as ctk

from neko_launcher.ui.views.dashboard_view import DashboardView


def test_dashboard_view_source_has_no_customer_management_controls() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "neko_launcher"
        / "ui"
        / "views"
        / "dashboard_view.py"
    ).read_text(encoding="utf-8")

    # Verify coupon controls absent from DashboardView class
    assert "self._coupon_entry" not in source
    assert "self._redeem_button" not in source
    assert "เติมวันจากคูปอง" not in source

    # Verify password & logout action buttons absent from DashboardView class
    assert "on_change_password" not in source.split("class DashboardView")[1].split("def open_password_dialog")[0]
    assert "on_sign_out" not in source
    assert "ออกจากระบบ" not in source

    # Verify game path entry & browse absent
    assert "self._game_path_entry" not in source
    assert "on_choose_game" not in source
    assert "เลือกไฟล์ (Browse)" not in source

    # Verify tweaker launch button absent
    assert "self._launch_game_button" not in source
    assert "เปิดโปรแกรม PSO2 Tweaker" not in source

    # Verify debug button & raw diagnostics absent
    assert "DEBUG MODE" not in source
    assert "TCP:" not in source
    assert "DNS:" not in source
    assert "ส่งข้อมูล (TX)" not in source
    # Verify ping action absent (but Ping label is allowed)
    assert "ping" not in source.split("class DashboardView")[1]
    assert "ACTIVE" not in source.split("class DashboardView")[1].split("def update_status_role")[0]


def test_dashboard_view_construction_and_bindings() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        status_title_var = tk.StringVar(value="● พร้อมใช้งาน")
        status_subtitle_var = tk.StringVar(value="กำลังรอเปิด PSO2")
        account_var = tk.StringVar(value="testuser@example.com")
        entitlement_days_var = tk.StringVar(value="เหลือ 30 วัน")
        entitlement_expiry_var = tk.StringVar(value="28/10/2026 12:00")
        server_status_var = tk.StringVar(value="ออนไลน์")
        download_speed_var = tk.StringVar(value="1.5 MB/s")
        upload_speed_var = tk.StringVar(value="500.0 KB/s")
        session_duration_var = tk.StringVar(value="01:23:45")
        latency_var = tk.StringVar(value="38 ms")

        view = DashboardView(
            root,
            root,
            status_title_var=status_title_var,
            status_subtitle_var=status_subtitle_var,
            account_var=account_var,
            entitlement_days_var=entitlement_days_var,
            entitlement_expiry_var=entitlement_expiry_var,
            server_status_var=server_status_var,
            download_speed_var=download_speed_var,
            upload_speed_var=upload_speed_var,
            session_duration_var=session_duration_var,
            latency_var=latency_var,
        )

        assert view.frame is not None
        assert str(view._status_title_label.cget("textvariable")) == str(status_title_var)
        assert str(view._status_subtitle_label.cget("textvariable")) == str(status_subtitle_var)
        assert str(view._entitlement_days_label.cget("textvariable")) == str(entitlement_days_var)

        # Aggregate traffic lives inside the connection section.
        assert str(view._connection_diagram._download_value_label.cget("textvariable")) == str(download_speed_var)
        assert str(view._connection_diagram._upload_value_label.cget("textvariable")) == str(upload_speed_var)
        assert not hasattr(view, "_dl_metric")
        assert not hasattr(view, "_uptime_metric")
        assert not hasattr(view, "_latency_metric")
        assert not hasattr(view, "_server_status_value")

        download_speed_var.set("—")
        upload_speed_var.set("—")
        assert download_speed_var.get() == "—"
        assert upload_speed_var.get() == "—"

        view.update_status_role("warning")
        view.update_status_role("danger")
        view.update_status_role("success")

        view.set_tier_badge("ใช้งานได้", role="success")
        view.set_tier_badge("หมดอายุ", role="danger")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_dashboard_view_initial_default_unknown_values() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        status_title_var = tk.StringVar(value="")
        status_subtitle_var = tk.StringVar(value="")
        account_var = tk.StringVar(value="")
        entitlement_days_var = tk.StringVar(value="")
        entitlement_expiry_var = tk.StringVar(value="")
        server_status_var = tk.StringVar(value="ออฟไลน์")
        download_speed_var = tk.StringVar(value="—")
        upload_speed_var = tk.StringVar(value="—")
        session_duration_var = tk.StringVar(value="—")
        latency_var = tk.StringVar(value="—")

        view = DashboardView(
            root,
            root,
            status_title_var=status_title_var,
            status_subtitle_var=status_subtitle_var,
            account_var=account_var,
            entitlement_days_var=entitlement_days_var,
            entitlement_expiry_var=entitlement_expiry_var,
            server_status_var=server_status_var,
            download_speed_var=download_speed_var,
            upload_speed_var=upload_speed_var,
            session_duration_var=session_duration_var,
            latency_var=latency_var,
        )

        assert download_speed_var.get() == "—"
        assert upload_speed_var.get() == "—"
        assert not hasattr(view, "_dl_metric")
        assert not hasattr(view, "_server_status_value")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_dashboard_view_composes_new_p2_components() -> None:
    source = Path(__file__).parents[2].joinpath('src', 'neko_launcher', 'ui', 'views', 'dashboard_view.py').read_text(encoding='utf-8')
    assert 'ConnectionDiagram' in source
    assert 'MetricCard' not in source
    assert 'def set_network_path' in source


def test_a20_dashboard_compact_contract() -> None:
    source = Path(__file__).parents[2].joinpath("src", "neko_launcher", "ui", "views", "dashboard_view.py").read_text(encoding="utf-8")
    assert "สถานะเซิร์ฟเวอร์" not in source
    assert "MetricCard(" not in source
    assert "download_var=download_speed_var" in source
    assert "upload_var=upload_speed_var" in source
