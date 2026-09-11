def should_trigger(changed_files: list[str]) -> bool:
    ignored_prefixes = ('docs/', 'tests/', '.github/', 'README.md', 'CHANGELOG.md')
    for f in changed_files:
        if not f.startswith(ignored_prefixes):
            return True
    return False
