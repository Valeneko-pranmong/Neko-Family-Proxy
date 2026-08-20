import tkinter as tk

import customtkinter as ctk
import pytest

from neko_launcher.ui import settings_window


def test_customer_membership_status_is_status_only_and_truthful() -> None:
    present = getattr(settings_window, "customer_membership_status")

    assert (
        present(
            "ใช้งานได้ • เหลือประมาณ 69 วัน • หมดอายุ 28/10/2026 10:23"
        )
        == "ใช้งานได้"
    )
    assert present("ใช้งานได้ • ไม่จำกัดวัน") == "ใช้งานได้"
    assert (
        present("สิทธิ์หมดอายุแล้ว • จะตัดการเชื่อมต่อหลังออกจากเกม")
        == "หมดอายุ"
    )
    assert present("หมดอายุแล้ว • เหลือ 0 วัน • 28/10/2026 10:23") == "หมดอายุ"


@pytest.mark.parametrize(
    "authority",
    [
        "เหลือ 0 วัน • เติมวันด้วยคูปองเพื่อเริ่มต้น",
        "ไม่สามารถใช้งานได้",
        "unexpected internal state",
        "",
    ],
)
def test_customer_membership_status_fails_closed(authority: str) -> None:
    present = getattr(settings_window, "customer_membership_status")

    assert present(authority) == "ไม่พร้อมใช้งาน"


def test_subscription_rows_keep_separate_shared_authorities() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        status_var = ctk.StringVar(
            master=root,
            value="ใช้งานได้ • เหลือประมาณ 69 วัน • หมดอายุ 28/10/2026 10:23",
        )
        days_var = ctk.StringVar(master=root, value="เหลือประมาณ 69 วัน")
        expiry_var = ctk.StringVar(master=root, value="28/10/2026 10:23")
        window = settings_window.SettingsWindow(
            root,
            entitlement_status_var=status_var,
            entitlement_days_var=days_var,
            entitlement_expiry_var=expiry_var,
        )

        status_value = window._customer_membership_status_var.get()
        assert status_value == "ใช้งานได้"
        assert "69 วัน" not in status_value
        assert "28/10/2026" not in status_value
        assert str(window._entitlement_status_label.cget("textvariable")) == str(
            window._customer_membership_status_var
        )
        assert str(window._entitlement_days_label.cget("textvariable")) == str(days_var)
        assert str(window._entitlement_expiry_label.cget("textvariable")) == str(
            expiry_var
        )
        assert days_var.get() == "เหลือประมาณ 69 วัน"
        assert expiry_var.get() == "28/10/2026 10:23"

        status_var.set("หมดอายุแล้ว • เหลือ 0 วัน • 28/10/2026 10:23")
        assert window._customer_membership_status_var.get() == "หมดอายุ"

        status_var.set("unknown")
        assert window._customer_membership_status_var.get() == "ไม่พร้อมใช้งาน"
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_subscription_window_destroy_removes_membership_status_trace() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        status_var = ctk.StringVar(master=root, value="ใช้งานได้")
        window = settings_window.SettingsWindow(
            root, entitlement_status_var=status_var
        )
        trace_id = window._entitlement_status_trace_id

        assert any(trace_id in callback for _, callback in status_var.trace_info())

        window.destroy()

        assert all(trace_id not in callback for _, callback in status_var.trace_info())
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_subscription_coupon_contract_remains_unchanged() -> None:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        pytest.skip("Tkinter display not available")

    try:
        coupon_var = ctk.StringVar(master=root, value="")
        redeemed: list[str] = []
        window = settings_window.SettingsWindow(
            root,
            coupon_var=coupon_var,
            on_redeem_coupon=lambda: redeemed.append(coupon_var.get()),
        )

        assert window._coupon_entry.cget("placeholder_text") == "กรอกรหัสคูปอง"
        assert window._coupon_entry._placeholder_text_active is True
        window._coupon_entry.focus_set()
        window._coupon_entry.insert(0, "NEKO-B31")
        window._redeem_coupon_button.invoke()
        assert coupon_var.get() == "NEKO-B31"
        assert redeemed == ["NEKO-B31"]
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
