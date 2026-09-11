def should_trigger(changed_files: list[str]) -> bool:
    ignored_prefixes = (
        'docs/', 'tests/', '.github/',
        'README.md', 'CHANGELOG.md', 'SECURITY.md', 'CONTRIBUTING.md',
        'scripts/kanban_release_adapter.py',
        'scripts/release_controller.py',
        'scripts/derive_version.py',
        'scripts/publish_atomic_release.py',
        'scripts/build_software_release_v2.py',
        'scripts/ci_change_classifier.py',
        'release_target.json'
    )
    for f in changed_files:
        if f.startswith(ignored_prefixes):
            continue
        # Also ignore nested test directories like agent/tests/
        if '/tests/' in f:
            continue
        return True
    return False
