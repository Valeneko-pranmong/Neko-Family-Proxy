alter table public.audit_events
  drop constraint if exists audit_events_event_type_check;

alter table public.audit_events
  add constraint audit_events_event_type_check
  check (
    event_type in (
      'session_claimed',
      'session_revoked',
      'session_rejected',
      'license_rejected',
      'coupon_batch_created',
      'coupon_redeemed',
      'coupon_batch_revoked',
      'coupon_batch_deleted',
      'admin_user_status_changed',
      'admin_license_revoked',
      'admin_license_extended',
      'admin_session_revoked',
      'admin_password_reset'
    )
  );
