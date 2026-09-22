"""Build the crawler Lambda deployment package.

Installs the crawler's dependencies (pure-Python, so safe to build on
Windows/macOS for the Linux Lambda runtime) and copies the crawler source
into infra/lambda_build/crawler/. Run this before `cdk deploy` and again
any time crawler/ changes — infra/infra/pipeline_stack.py references this
prebuilt folder directly, with no Docker image involved.

Usage:
    python build_lambda.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Same non-ASCII-path issue as the pip subprocess below, but for this
# script's own stdout on a default-cp1252 Windows console.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CRAWLER_DIR = Path(__file__).resolve().parent
BUILD_DIR = CRAWLER_DIR.parent / "infra" / "lambda_build" / "crawler"


def main():
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # Force UTF-8 for pip's own output — on Windows, a project path with
    # non-ASCII characters (e.g. Vietnamese diacritics) makes pip crash
    # while trying to print progress through the default cp1252 console
    # encoding, even though the install itself would have succeeded.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(CRAWLER_DIR / "requirements.txt"),
            "-t",
            str(BUILD_DIR),
        ],
        check=True,
        env=env,
    )

    for py_file in CRAWLER_DIR.glob("*.py"):
        if py_file.name != "build_lambda.py":
            shutil.copy(py_file, BUILD_DIR / py_file.name)

    print(f"Lambda package built at {BUILD_DIR}")


if __name__ == "__main__":
    main()
