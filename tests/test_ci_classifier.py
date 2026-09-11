def test_classifier_skips_docs():
    from scripts.ci_change_classifier import should_trigger
    assert not should_trigger(["docs/README.md", "tests/test_x.py"])
    assert should_trigger(["src/main.py", "docs/README.md"])
