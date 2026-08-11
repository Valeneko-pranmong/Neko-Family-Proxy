from neko_launcher.e2e.final_windows_harness import parse_launcher_stage_trace


def test_stage_trace_parser_reads_real_logger_shape_and_terminal_core_status() -> None:
    stages = (
        "GAME_PROCESS_DETECTED",
        "PROXY_START_REQUESTED",
        "COMMAND_VALIDATE",
        "ACCESS_CONTEXT_VALIDATE",
        "TARGET_WAIT",
        "HOST_START",
        "CONTROL_CHANNEL_WAIT",
        "RUNTIME_CONFIG_CATALOG",
        "RUNTIME_CONFIG_VALIDATE",
        "TARGET_RECHECK",
        "CHALLENGE_REQUEST",
        "TARGET_BIND",
        "PERMIT_REQUEST",
        "AUTHORIZED_START",
        "RUNNING_VERIFY",
    )
    log_text = "\n".join(
        f"[10:00:00.000] [DBG-abc123] [CORE] [{stage}]" for stage in stages
    )
    log_text += (
        "\n[10:00:01.000] [DBG-abc123] [CORE] [CORE_STATUS] "
        "status=CoreStatus.RUNNING\n"
    )

    trace = parse_launcher_stage_trace(log_text)

    trace.validate_success()
    assert trace.stages == stages
    assert trace.final_core_status == "CoreStatus.RUNNING"
