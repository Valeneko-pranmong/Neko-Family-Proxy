# Single-Repo Planning Self-Review Checklist

- [x] Spec coverage: every approved spec requirement maps to RA, RT, or INT tasks.
- [x] Placeholder scan: no TBD/TODO/"similar to" steps; protocol ellipses are explicitly identified as Python Protocol syntax only.
- [x] Type/interface consistency: planned interfaces are centralized in `2026-09-16-single-repo-plan-contracts.md`; later tasks consume those contracts or exact accepted equivalents.
- [x] TDD specificity: every code-changing task starts with RED tests before production edits; companion contracts provide concrete first RED cases and required algorithms.
- [x] Review gates: each task has independent C0/I0 before dependent tasks.
- [x] Authority safety: no implementation task grants production signing/public mutation/private-key access.
- [x] seq8 safety: old SIGNED bytes immutable; real FAILED append remains a separate Owner gate.
- [x] Repo topology: old Updates repo is rejected; no create/bootstrap action remains.
- [x] Updater lifecycle: 5.x Updater never self-updates; corrupt/incompatible helper means reinstall.
- [x] Repair semantics: user action only; exact installed release; Launcher/Core only; no implicit update.
- [x] Machine binding: OS-protected credential plus server authority; no hardware fingerprint as secret.
- [x] Major boundary: 5.x -> 6.x clean reinstall only.
- [x] Session behavior: new login invalidates old active session.

## Coverage map

| Spec requirement | Plan task |
| --- | --- |
| Single canonical repo / no Updates repo | RA-SR2, RA-SR3, RA-SR4 |
| Full five authored assets every 5.x Release | RA-SR3, RA-SR4, INT-SR3 |
| Mandatory newer 5.x / no Skip-Later | RT-SR1, INT-SR3 |
| Updater fixed during 5.x | RT-SR2, RT-SR5, INT-SR3 |
| Updater bad => reinstall | RT-SR2, RT-SR8 |
| 5.x -> 6.x reinstall | RT-SR1, RT-SR8 |
| File Check read-only | RT-SR4, RT-SR8 |
| Explicit exact-release Repair | RT-SR3, RT-SR5, RT-SR8 |
| Direct Asset not portable | RT-SR6, RT-SR8 |
| Copied install rejected | RT-SR6, RT-SR8 |
| Reinstall/new disk self-service | RT-SR6, RT-SR7 |
| Single active session preserved | RT-SR7, RT-SR8 |
| Signed seq8 safe supersession | RA-SR1, INT-SR4 |
| Unified publisher + hosted readback | RA-SR3, RA-SR4, RA-SR5 |
| Public mutations remain fresh Owner gates | INT-SR4 |
