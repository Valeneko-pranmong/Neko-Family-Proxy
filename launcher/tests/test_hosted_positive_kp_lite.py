from __future__ import annotations

from unittest.mock import create_autospec

from neko_launcher.application.authorized_core import (
    CoreChallenge,
    LaunchPermitGateway,
    OpaquePermit,
)
from neko_launcher.e2e.hosted_positive_kp import RecordingPermitGateway


def test_recording_permit_gateway_delegates_only_lite_arguments() -> None:
    delegate = create_autospec(LaunchPermitGateway)
    delegate.issue_launch_permit.return_value = OpaquePermit("permit")
    gateway = RecordingPermitGateway(delegate)
    challenge = CoreChallenge("A" * 43)

    result = gateway.issue_launch_permit(
        authenticated_transport="transport",
        correlation_id="0123456789abcdef0123456789abcdef",
        challenge=challenge,
        timeout=10.0,
    )

    assert result.reveal_for_transport() == "permit"
    assert gateway.issued_count == 1
    delegate.issue_launch_permit.assert_called_once_with(
        "transport",
        "0123456789abcdef0123456789abcdef",
        challenge,
        10.0,
    )
