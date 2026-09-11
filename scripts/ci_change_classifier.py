def should_trigger(changed_files: list[str]) -> bool:
    ignored_prefixes = (
        'docs/', 'tests/', '.github/',
        'README.md', 'CHANGELOG.md', 'SECURITY.md', 'CONTRIBUTING.md',
        'scripts/kanban_release_adapter.py',
        'scripts/release_controller.py',
        'scripts/derive_version.py',
        'scripts/publish_atomic_release.py'
    )
    for f in changed_files:
        if not f.startswith(ignored_prefixes):
            return True
    return False
