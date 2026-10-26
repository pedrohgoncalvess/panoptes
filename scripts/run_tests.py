"""Run pytest and clean generated caches even when tests fail."""

import os
import subprocess
import sys

from clean_caches import ROOT, clean_caches


def main():
    arguments = sys.argv[1:]
    if any(
        value == "--basetemp" or value.startswith("--basetemp=") for value in arguments
    ):
        raise SystemExit("The test runner manages --basetemp inside the workspace")
    result = 1
    try:
        result = subprocess.call(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                *arguments,
                f"--basetemp={ROOT / ('.pytest-tmp-run-' + str(os.getpid()))}",
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    finally:
        try:
            removed = clean_caches()
            print(f"Caches cleaned: {len(removed)} directories", flush=True)
        except OSError as error:
            print(f"Cache cleanup failed: {error}", file=sys.stderr)
            if result == 0:
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
