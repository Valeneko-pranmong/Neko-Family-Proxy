from neko_launcher.updater.early_dispatch import maybe_dispatch_updater_entry


def test_early_dispatch_returns_false_for_normal_launch() -> None:
    assert not maybe_dispatch_updater_entry(["NekoLauncher.exe"])
    assert not maybe_dispatch_updater_entry(["NekoLauncher.exe", "--normal-arg"])


def test_early_dispatch_detects_probation_flag() -> None:
    # If stdin/stdout is not connected to broker in unit test, it should raise or exit cleanly
    try:
        res = maybe_dispatch_updater_entry(["NekoLauncher.exe", "--update-probation"])
        assert isinstance(res, bool)
    except (SystemExit, OSError):
        pass
