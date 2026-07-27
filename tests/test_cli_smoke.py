"""Prove the tool is human-runnable from a plain shell — no agent/harness.

Each test runs `python3 -m open_audio_fetch ...` as a real subprocess with only
PYTHONPATH set, and asserts a clean exit. If any of these fail, the CLI has
grown a hidden dependency on its runtime environment.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run(*args):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, "-m", "open_audio_fetch", *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


class TestCliSmoke(unittest.TestCase):
    def test_version(self):
        r = run("--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("open-audio-fetch", r.stdout + r.stderr)

    def test_list_sites(self):
        r = run("--list-sites")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("internetarchive", r.stdout)

    def test_catalog(self):
        r = run("--catalog")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("free-audio sources", r.stdout)

    def test_validate_catalog(self):
        r = run("--validate-catalog")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("catalog OK", r.stdout)

    def test_missing_api_key_is_clean_error_not_crash(self):
        # jamendo needs a key; a human running it should get a message + exit 2,
        # never a traceback.
        env_clean = {k: v for k, v in os.environ.items() if k != "JAMENDO_CLIENT_ID"}
        env_clean["PYTHONPATH"] = str(SRC)
        r = subprocess.run(
            [sys.executable, "-m", "open_audio_fetch", "jamendo", "--dry-run"],
            capture_output=True, text=True, env=env_clean, cwd=str(ROOT),
        )
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("JAMENDO_CLIENT_ID", r.stderr)


if __name__ == "__main__":
    unittest.main()
