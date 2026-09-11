from neko_launcher.ui.update_banner import UpdateBannerController


def test_banner_hidden_when_no_update() -> None:
    ctrl = UpdateBannerController()
    state = ctrl.update_status(has_update=False, is_proxy_active=False)
    assert not state.visible


def test_banner_visible_and_enabled_when_update_available_and_idle() -> None:
    ctrl = UpdateBannerController()
    state = ctrl.update_status(has_update=True, is_proxy_active=False, version="5.1.0a3")
    assert state.visible
    assert state.restart_enabled
    assert state.busy_warning is None
    assert "5.1.0a3" in state.message


def test_banner_disabled_when_proxy_active() -> None:
    ctrl = UpdateBannerController()
    state = ctrl.update_status(has_update=True, is_proxy_active=True, version="5.1.0a3")
    assert state.visible
    assert not state.restart_enabled
    assert state.busy_warning is not None
    assert "กรุณาหยุดการเชื่อมต่อ" in state.busy_warning
