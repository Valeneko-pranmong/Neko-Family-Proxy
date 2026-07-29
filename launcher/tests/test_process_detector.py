from neko_launcher.infrastructure.process_detector import PSO2_PROCESS_NAMES


def test_auto_connect_watches_only_the_running_game_process() -> None:
    assert PSO2_PROCESS_NAMES == frozenset({"pso2.exe"})
