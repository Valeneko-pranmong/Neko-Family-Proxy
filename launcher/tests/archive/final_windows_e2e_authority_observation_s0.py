from datetime import UTC, datetime, timedelta

from neko_launcher.e2e.final_windows_harness import (
    AuthorityState,
    BackendAuthorityObservation,
    ExistingPermitWindow,
    InstanceId,
)


def test_backend_observation_separates_existing_permit_from_future_eligibility() -> None:
    replaced_at = datetime(2026, 8, 11, 10, 0, 0, tzinfo=UTC)
    observation = BackendAuthorityObservation(
        observed_at=replaced_at + timedelta(seconds=3),
        instance=InstanceId.INSTANCE_A,
        session_ref="sid_aaaaaaaaaaaaaaaa",
        installation_ref="iid_aaaaaaaaaaaaaaaa",
        authority_state=AuthorityState.INACTIVE,
        heartbeat_accepted=False,
        future_permit_eligible=False,
        authority_replaced_at=replaced_at,
        authority_loss_detected_at=replaced_at + timedelta(seconds=2),
        existing_permit_window=ExistingPermitWindow(
            issued_at=replaced_at - timedelta(seconds=1),
            expires_at=replaced_at + timedelta(seconds=29),
        ),
    )

    observation.validate()

    assert observation.existing_permit_window is not None
    assert observation.future_permit_eligible is False
