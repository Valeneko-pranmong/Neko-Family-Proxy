import yaml
from pathlib import Path

def test_acceptance_workflow_permissions():
    wf_path = Path(".github/workflows/main_source_acceptance.yml")
    if not wf_path.exists():
        return
    with open(wf_path) as f:
        wf = yaml.safe_load(f)
    
    assert wf.get("permissions") == {"contents": "read"}

def test_acceptance_workflow_steps():
    wf_path = Path(".github/workflows/main_source_acceptance.yml")
    if not wf_path.exists():
        return
    with open(wf_path) as f:
        wf = yaml.safe_load(f)
        
    jobs = wf["jobs"]["acceptance"]
    assert "release_eligible" in jobs.get("outputs", {})
    assert jobs["outputs"]["release_eligible"] == "${{ steps.classify.outputs.release_eligible }}"
    
    steps = jobs["steps"]
    
    classify_step = next(s for s in steps if s.get("id") == "classify")
    assert "GITHUB_OUTPUT" in classify_step["run"]
    assert "sys.exit(78)" not in classify_step["run"]
    
    # Check conditional execution
    conditional_steps = [s for s in steps if s.get("if")]
    assert len(conditional_steps) >= 3
    for s in conditional_steps:
        assert s["if"] == "${{ steps.classify.outputs.release_eligible == 'true' }}" or s["if"] == "steps.classify.outputs.release_eligible == 'true'"
        
    # Check if specific commands run
    run_commands = [s.get("run", "") for s in steps]
    assert any("ruff" in cmd for cmd in run_commands)
    assert any("scripts/check_repository_safety.py" in cmd for cmd in run_commands)
    assert any("pytest" in cmd and "not integration" in cmd for cmd in run_commands)
