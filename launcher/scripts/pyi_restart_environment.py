import os
import subprocess
import sys

if (
    getattr(sys, "frozen", False)
    and not {"--update-managed", "--update-probation"}.intersection(sys.argv[1:])
    and not os.path.isfile(os.path.join(sys._MEIPASS, "pyi_restart_environment.py"))
):
    # Older one-file parents can pass an extraction tree from a different build.
    restart_env = os.environ.copy()
    restart_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    restarted = subprocess.Popen([sys.executable, *sys.argv[1:]], env=restart_env)
    if sys.argv[1:] == ["--tk-self-test"]:
        sys.exit(restarted.wait())
    sys.exit(0)
