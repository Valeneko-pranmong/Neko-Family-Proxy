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
    assert "รับข้อมูล (RX)" not in source
    assert "ส่งข้อมูล (TX)" not in source


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
        download_speed_var = tk.StringVar(value="1.5 MB/s")
        upload_speed_var = tk.StringVar(value="500.0 KB/s")
        session_duration_var = tk.StringVar(value="01:23:45")

        view = DashboardView(
            root,
            root,
            status_title_var=status_title_var,
            status_subtitle_var=status_subtitle_var,
            account_var=account_var,
            entitlement_days_var=entitlement_days_var,
            entitlement_expiry_var=entitlement_expiry_var,
            download_speed_var=download_speed_var,
            upload_speed_var=upload_speed_var,
            session_duration_var=session_duration_var,
        )

        assert view.frame is not None
        assert str(view._status_title_label.cget("textvariable")) == str(status_title_var)
        assert str(view._status_subtitle_label.cget("textvariable")) == str(status_subtitle_var)
        assert str(view._entitlement_days_label.cget("textvariable")) == str(entitlement_days_var)

        view.update_status_role("warning")
        view.update_status_role("danger")
        view.update_status_role("success")
    finally:
        try:
            root.destroy()
        except Exception:
            pass
