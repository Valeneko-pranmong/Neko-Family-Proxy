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

def test_classifier_a4867ad_regression():
    from scripts.ci_change_classifier import should_trigger
    # Exact changed-file set from main merge a4867ad72c00971efda29f79d8696283502e2112
    changed_files = [
        "agent/tests/test_operations_hardening.py",
        "agent/tests/test_weekly_maintenance.py",
        "scripts/build_software_release_v2.py",
        "scripts/ci_change_classifier.py",
        "scripts/derive_version.py",
        "scripts/kanban_release_adapter.py",
        "scripts/publish_atomic_release.py",
        "scripts/release_controller.py",
        "tests/e2e_test_release_pipeline.py",
        "tests/test_ci_classifier.py",
        "tests/test_derive_version.py",
        "tests/test_e2e_release_pipeline.py",
        "tests/test_kanban_adapter.py",
        "tests/test_publish.py"
    ]
    assert not should_trigger(changed_files)

def test_classifier_product_files():
    from scripts.ci_change_classifier import should_trigger
    # installer/runtime and Core/product code must remain release-eligible
    assert should_trigger(["installer/build.iss"])
    assert should_trigger(["updater/runtime.go"])
    assert should_trigger(["Core/product.cs"])
    assert should_trigger(["launcher/src/main.rs"])
    # mixed tests
    assert should_trigger(["agent/tests/test_foo.py", "Core/product.cs"])
