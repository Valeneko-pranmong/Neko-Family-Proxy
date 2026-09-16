# Single-Repo Orchestra Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for task execution and review isolation. Each child plan is authoritative for its own workstream.

**Goal:** Coordinate the approved single-repo architecture into parallel, independently reviewed workstreams and integrate only accepted commits.

**Architecture:** Release-authority/publisher work and runtime/integrity work may execute in parallel because they own mostly separate files and security concerns. Integration starts only after both workstreams reach C0/I0. Public production actions stay behind fresh Owner gates.

**Tech Stack:** Hermes Kanban orchestration, Git worktrees, Python/pytest/Ruff/PyInstaller, independent reviewer profile.

**Spec:** `docs/superpowers/specs/2026-09-16-single-repo-unified-release-design.md`

**Execution contracts:** `docs/superpowers/plans/2026-09-16-single-repo-plan-contracts.md`

## Child plans

1. `docs/superpowers/plans/2026-09-16-single-repo-release-authority-publisher.md`
2. `docs/superpowers/plans/2026-09-16-single-repo-runtime-integrity-repair.md`
3. `docs/superpowers/plans/2026-09-16-single-repo-integration-acceptance.md`

## DAG

```text
APPROVED SPEC bf1eccf29f8373e768805374d9355ff4cff1bcda
        |
        +---------------------------+
        |                           |
        v                           v
  RA-SR1 -> RA-SR2 -> RA-SR3 -> RA-SR4 -> RA-SR5
  RT-SR1 -> RT-SR2 -> RT-SR3 -> RT-SR4 -> RT-SR5 -> RT-SR6 -> RT-SR7 -> RT-SR8
        \                           /
         \_________________________/
                      |
                      v
                  INT-SR1/2
                      |
                      v
                   INT-SR3
                      |
                      v
                   FINAL C0/I0
                      |
                      v
        fresh exact Owner production gates
```

## Controller rules

- Never dispatch a child whose parent review is not explicit C0/I0.
- RA and RT workstreams may run concurrently, but tasks inside each workstream remain sequential behind their own review gate.
- Implementation worker and independent reviewer must be different runs; reviewer is read-only and must not fix findings.
- Any Critical/Important finding creates a remediation child and a fresh independent re-review.
- Worker branches/worktrees are isolated; controller alone integrates accepted commits.
- No worker gets production private-key access or public GitHub mutation authority.
- No public repository creation is permitted; `Neko-Family-Proxy-Updates` remains superseded.
- Controller may use `cx/gpt-5.6-sol high` only for genuinely difficult remediation/architecture reasoning, one escalation at a time; routine tasks use normal worker profiles.
- Stall detection must inspect process descendants/logs/git/file progress, not wrapper heartbeat alone.
- All implementation workers read the approved spec, their child plan, and the execution-contract companion before editing.
