def test_classifier_skips_docs_and_ci_only():
    from scripts.ci_change_classifier import should_trigger
    # docs/test/CI-only changes must result in release_eligible=false (should_trigger=False)
    assert not should_trigger(["docs/README.md"])
    assert not should_trigger(["tests/test_ci_classifier.py"])
    assert not should_trigger([".github/workflows/main_source_acceptance.yml"])
    assert not should_trigger(["README.md"])
    assert not should_trigger(["CHANGELOG.md"])
    assert not should_trigger(["docs/README.md", "tests/test_x.py"])
    
    # Release controller infra scripts should not trigger release
    assert not should_trigger(["scripts/kanban_release_adapter.py"])
    assert not should_trigger(["scripts/release_controller.py"])
    assert not should_trigger(["scripts/derive_version.py"])
    assert not should_trigger(["scripts/publish_atomic_release.py"])
    assert not should_trigger(["scripts/derive_version.py", "scripts/release_controller.py"])

def test_classifier_mixed_changes_trigger():
    from scripts.ci_change_classifier import should_trigger
    # Product-impacting and mixed changes must set release_eligible=true
    assert should_trigger(["src/main.py"])
    assert should_trigger(["src/main.py", "docs/README.md"])
    assert should_trigger(["scripts/check_repository_safety.py"])
    assert should_trigger(["launcher/src/main.py", "tests/test_x.py"])
