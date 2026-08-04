# Historical documentation archive

Documents in this directory are retained for traceability only. They may contain
stale paths, commit hashes, test counts, artifact hashes, or design proposals.
Do not use them as current build, release, or implementation instructions.

| Historical document | Why archived | Current replacement |
| --- | --- | --- |
| [`launcher-s0-connector-handoff.md`](launcher-s0-connector-handoff.md) | Commit-specific partial implementation evidence from before the accepted baseline candidate | [`../launcher-production-adapters.md`](../launcher-production-adapters.md) |
| [`launcher-core-authorization-adapter-draft.md`](launcher-core-authorization-adapter-draft.md) | Integration draft superseded by the central `s0-rc1` handoff | [`../neko-auth-s0-production-handoff.md`](../neko-auth-s0-production-handoff.md) |
| [`launcher-s0-contract-proposal.md`](launcher-s0-contract-proposal.md) | Launcher proposal predating the cross-team baseline | [`../neko-auth-s0-production-handoff.md`](../neko-auth-s0-production-handoff.md) |
| [`s0-security-contract-freeze-request.md`](s0-security-contract-freeze-request.md) | Request that led to the later technical baseline; references another repository | [`../neko-auth-s0-production-handoff.md`](../neko-auth-s0-production-handoff.md) |
| [`password-recovery-smtp-status.md`](password-recovery-smtp-status.md) | SMTP/email recovery was retired; its final line referenced a deleted handoff | [`../../launcher/README.md`](../../launcher/README.md) and [`../../supabase/README.md`](../../supabase/README.md) |
| [`launcher-release-candidate-2026-07-29.md`](launcher-release-candidate-2026-07-29.md) | Dated artifact and deployment evidence; not the current release state | [`../README.md`](../README.md) |
| [`change-log-2026-07.md`](change-log-2026-07.md) | Historical work log with completed and stale next steps | Git history and current component documentation |

The archive is not a place for new active requirements. Promote valid information
to a current document instead of updating an archived record in place.
