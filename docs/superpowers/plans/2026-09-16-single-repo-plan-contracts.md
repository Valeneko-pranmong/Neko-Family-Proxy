# Single-Repo Plan Execution Contracts

This companion file makes task interfaces and first RED tests explicit for the three implementation plans. Workers must read it together with their assigned child plan. Names below are the planned contracts; if an accepted existing type already owns the same responsibility, reuse that type while preserving these semantics and record the exact reused symbol in the task result.

## Release authority / publisher contracts

### Seq8 supersession request

```python
@dataclass(frozen=True)
class SupersedeSignedReleaseRequest:
    sequence: int
    release_id: str
    source_commit: str
    component_set_sha256: str
    payload_sha256: str
    envelope_sha256: str
    latest_ledger_entry_sha256: str
    approved_spec_commit: str
    reason_code: Literal["ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION"]
```

Controller semantics:

```text
validate request against verified ledger + custody under authority lock
require current exact state == SIGNED and no PUBLISHED record
require every identity/hash in request matches current authority state
prepare exactly one FAILED event using existing append-only primitives
reconcile and prove next_unused_sequence > 8
implementation mode uses mutate=false against real production authority
production mutation remains a separate Owner gate
```

First RED cases:

```python
def test_supersede_signed_unpublished_release_prepares_terminal_failed_event():
    result = prepare_signed_release_supersession(
        verified_ledger=ledger_with_seq8_signed(),
        custody=custody_with_exact_seq8_envelope(),
        request=exact_seq8_request(),
    )
    assert result.event.sequence == 8
    assert result.event.status == "FAILED"
    assert result.next_unused_sequence == 9


def test_supersession_rejects_published_release_before_append():
    with pytest.raises(ReleaseAuthorityReconciliationRequired):
        prepare_signed_release_supersession(
            verified_ledger=ledger_with_seq8_published(),
            custody=custody_with_exact_seq8_envelope(),
            request=exact_seq8_request(),
        )
```

### Unified authored asset set

```python
REQUIRED_UNIFIED_ASSETS: tuple[str, ...] = (
    "NekoFamilyProxy-Installer.exe",
    "release-v2.json",
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
)
```

Verifier contract:

```text
verify_unified_release_assets(
    release_json_path: Path,
    download_dir: Path,
    expected_tag: str,
    expected_target: str,
    require_draft: bool,
) -> None
```

First RED cases:

```python
def test_unified_release_requires_installer_and_all_machine_assets(tmp_path):
    release_path, download_dir = unified_release_fixture(
        tmp_path,
        asset_names=REQUIRED_UNIFIED_ASSETS,
        tag="v5.1.3",
        target="a" * 40,
        draft=True,
    )
    verify_unified_release_assets(
        release_json_path=release_path,
        download_dir=download_dir,
        expected_tag="v5.1.3",
        expected_target="a" * 40,
        require_draft=True,
    )


def test_old_updates_repository_is_not_a_production_publication_target():
    assert CANONICAL_REPO == "Valeneko-pranmong/Neko-Family-Proxy"
    assert CANONICAL_REPO != "Valeneko-pranmong/Neko-Family-Proxy-Updates"
```

### Unified publisher

Canonical publication entrypoint contract:

```text
publish_unified_release(
    tag: str,
    target_commit: str,
    staging_dir: Path,
    body: str,
    authority_binding: SignedReleaseBinding,
    executor: CommandExecutor | None = None,
    repo: str = CANONICAL_REPO,
) -> UnifiedPublishResult
```

Required algorithm:

```text
1. validate repo == Valeneko-pranmong/Neko-Family-Proxy
2. validate authority_binding.source_commit == target_commit while holding authority lock
3. validate local staging has exactly the five authored assets
4. create OR reconcile one matching draft for tag/target
5. upload missing assets only when local/remote identity is unambiguous
6. download every hosted authored asset by asset id
7. compare hosted size + SHA-256 to frozen staging bytes
8. re-read release metadata and run unified verifier
9. promote exactly once; crash retry reconciles rather than duplicates
```

First RED cases:

```python
def test_publish_unified_release_uploads_exact_five_assets(fake_executor, staging_dir, signed_binding):
    result = publish_unified_release(
        tag="v5.1.3",
        target_commit="a" * 40,
        staging_dir=staging_dir,
        body="Neko Family Proxy v5.1.3",
        authority_binding=replace(signed_binding, source_commit="a" * 40),
        executor=fake_executor,
    )
    assert result.repo == "Valeneko-pranmong/Neko-Family-Proxy"
    assert set(result.assets) == set(REQUIRED_UNIFIED_ASSETS)


def test_publish_refuses_target_not_equal_to_signed_source_commit(fake_executor, staging_dir, signed_binding):
    with pytest.raises(StageDraftReleaseError):
        publish_unified_release(
            tag="v5.1.3",
            target_commit="b" * 40,
            staging_dir=staging_dir,
            body="Neko Family Proxy v5.1.3",
            authority_binding=replace(signed_binding, source_commit="a" * 40),
            executor=fake_executor,
        )
    assert fake_executor.public_mutation_calls == []
```

## Runtime contracts

### Startup disposition

```python
class StartupUpdateDisposition(Enum):
    CURRENT = "current"
    MANDATORY_UPDATE = "mandatory_update"
    REINSTALL_REQUIRED = "reinstall_required"
```

Classification contract:

```text
classify_startup_release(
    local: LocalReleaseIdentity,
    remote: authenticated bound release,
) -> StartupUpdateDisposition
```

Required rules:

```text
remote invalid/untrusted/conflicting -> existing fail-closed error path
remote sequence == committed local sequence -> CURRENT only when identity matches exactly
remote sequence > local and remote major == 5 -> MANDATORY_UPDATE regardless of optional-looking manifest flag
remote major >= 6 or updater protocol incompatible with 5.x helper -> REINSTALL_REQUIRED
rollback/same-sequence-different-identity -> existing conflict/fail-closed path
```

First RED cases:

```python
def test_newer_same_major_is_mandatory_even_if_manifest_flag_false():
    result = classify_startup_release(
        local=local_release_identity(version="5.1.2", sequence=8),
        remote=bound_release(version="5.1.3", sequence=9, mandatory=False),
    )
    assert result is StartupUpdateDisposition.MANDATORY_UPDATE


def test_next_major_requires_reinstall():
    result = classify_startup_release(
        local=local_release_identity(version="5.1.3", sequence=9),
        remote=bound_release(version="6.0.0", sequence=10, mandatory=True),
    )
    assert result is StartupUpdateDisposition.REINSTALL_REQUIRED
```

### Installed updater verification

```python
@dataclass(frozen=True)
class InstalledUpdaterVerification:
    trusted: bool
    reinstall_required: bool
    expected_sha256: str
    actual_sha256: str | None
    reason: str | None
```

Contract:

```text
verify_installed_updater(
    updater_path: Path,
    bound_release: authenticated bound release,
    supported_protocol: int,
) -> InstalledUpdaterVerification
```

First RED case:

```python
def test_corrupt_updater_requires_reinstall(tmp_path, bound_release):
    updater_path = tmp_path / "NekoUpdater.exe"
    updater_path.write_bytes(b"tampered")
    result = verify_installed_updater(
        updater_path=updater_path,
        bound_release=bound_release_with_updater_sha(bound_release, "0" * 64),
        supported_protocol=1,
    )
    assert result.reinstall_required is True
    assert result.trusted is False
```

### Exact installed release identity

Extend accepted durable local identity with an exact hosted selector while preserving committed/high-water/observed/failed ordering.

```python
@dataclass(frozen=True)
class InstalledReleaseSelector:
    sequence: int
    release_id: str
    version: str
    tag_name: str
    target_commit: str
```

Resolver contract:

```text
resolve_exact_release(selector: InstalledReleaseSelector) -> authenticated bound release
```

The resolver requests the exact canonical tag/release identity and never calls GitHub `latest` for File Check/Repair.

First RED case:

```python
def test_file_check_resolves_exact_committed_tag_not_latest(fake_github):
    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    resolve_exact_release(client=fake_github, selector=selector)
    assert fake_github.requested_tag == "v5.1.3"
    assert fake_github.latest_requested is False
```

### File Check

```python
class IntegrityStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    UNTRUSTED_UPDATER = "untrusted_updater"


@dataclass(frozen=True)
class FileIntegrityItem:
    component: Literal["launcher", "updater", "core"]
    path: Path
    expected_size: int
    expected_sha256: str
    actual_size: int | None
    actual_sha256: str | None
    status: IntegrityStatus


@dataclass(frozen=True)
class FileIntegrityReport:
    selector: InstalledReleaseSelector
    items: tuple[FileIntegrityItem, ...]
    repairable_components: tuple[Literal["launcher", "core"], ...]
    reinstall_required: bool
```

Contract:

```text
check_installed_files(
    install_root: Path,
    release: authenticated exact bound release,
) -> FileIntegrityReport
```

Read-only RED proof:

```python
def test_file_check_has_no_mutation_dependency(tmp_path, exact_release):
    report = check_installed_files(install_root=tmp_path, release=exact_release)
    assert len(report.items) == 3
    assert not hasattr(report, "apply")
```

The production `check_installed_files` function must not accept downloader, stager, updater-session, or mutation callbacks. UI tests separately prove Check does not call Repair.

### Repair

```python
@dataclass(frozen=True)
class RepairRequest:
    selector: InstalledReleaseSelector
    components: tuple[Literal["launcher", "core"], ...]
```

Repair contract:

```text
repair_installed_release(
    request: RepairRequest,
    exact_release_resolver,
    updater_verifier,
    stage_service,
    updater_session,
) -> RepairResult
```

Required algorithm:

```text
1. validate components subset is non-empty and only launcher/core
2. resolve exact selector; reject latest substitution or different tag/sequence
3. revalidate installed updater trust/protocol
4. download only requested damaged component assets
5. verify size/SHA-256/signed release binding
6. stage via existing transaction path with repair intent
7. apply via validated updater IPC session
8. re-run File Check; success only when repaired items are OK
9. committed release identity/version remains unchanged
```

First RED cases:

```python
def test_repair_preserves_exact_installed_version(repair_dependencies):
    request = RepairRequest(
        selector=InstalledReleaseSelector(9, "stable-0009", "5.1.3", "v5.1.3", "a" * 40),
        components=("launcher",),
    )
    result = repair_installed_release(request=request, **repair_dependencies)
    assert result.before_version == "5.1.3"
    assert result.after_version == "5.1.3"
    assert result.resolved_tag == "v5.1.3"


def test_repair_request_cannot_include_updater():
    with pytest.raises(RepairNotAllowed):
        RepairRequest(
            selector=InstalledReleaseSelector(9, "stable-0009", "5.1.3", "v5.1.3", "a" * 40),
            components=("updater",),  # type: ignore[arg-type]
        )
```

### Machine-bound installation credential

Application-level interface:

```python
class InstallationCredentialProvider(Protocol):
    def provision(self) -> InstallationPublicIdentity: ...
    def load_public_identity(self) -> InstallationPublicIdentity: ...
    def prove(self, challenge: bytes) -> InstallationProof: ...
```

The ellipses above are Python Protocol syntax, not unfinished implementation text. Production Windows implementation keeps secret key material non-exportable through this interface. Tests inject a deterministic fake provider.

Required startup ordering:

```text
validate install root
load/validate Installer-provisioned machine credential
obtain/validate server challenge/proof as required by enrollment contract
only then compose normal login/service flow
```

First RED cases:

```python
def test_launcher_without_installer_credential_fails_before_login(fake_login):
    with pytest.raises(InstallationBindingRequired):
        bootstrap_runtime(
            credential_provider=missing_installation_credential_provider(),
            login_service=fake_login,
        )
    assert fake_login.calls == []


def test_copied_install_public_state_cannot_prove_on_second_machine():
    source = fake_installation_credential_provider(machine_name="A")
    public_state = source.provision().serialize_public_state()
    destination = fake_installation_credential_provider(
        machine_name="B",
        imported_public_state=public_state,
    )
    with pytest.raises(InstallationBindingInvalid):
        destination.prove(b"server-challenge")
```

## Integration contracts

Integration cards consume only exact reviewed commit SHAs. On conflict the only allowed sequence is:

```text
git cherry-pick <reviewed-sha>
# if conflict:
git cherry-pick --abort
# controller blocks integration and creates a remediation + re-review child
```

No integration worker may resolve source conflicts manually.

Final proof records these exact literals:

```text
NO_PRODUCTION_LEDGER_MUTATION=true
NO_PRODUCTION_SIGNING=true
NO_PUBLIC_GITHUB_MUTATION=true
NO_DESTRUCTIVE_ACTION=true
```
