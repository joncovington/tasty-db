import os
import subprocess
import sys


def test_cli_output_survives_a_non_utf8_pipe():
    """A cp1252 stdout (Windows redirect default) must not crash on → / —."""
    code = "from tastydb.cli import _utf8_stdio; _utf8_stdio(); print('a → b — c')"
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    assert out.stdout.decode("utf-8").strip() == "a → b — c"
