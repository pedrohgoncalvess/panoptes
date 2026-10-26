"""Enable browser connections locally without printing authentication secrets."""

import argparse
import base64
import re
import secrets
from pathlib import Path


def configure(path: Path, *, local=False):
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    values = {
        "BROWSER_SESSION_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "BROWSER_SERVICE_TOKEN": secrets.token_urlsafe(48),
        "BROWSER_SERVICE_URL": "http://localhost:8000"
        if local
        else "http://backend:8000",
    }
    for name, value in values.items():
        pattern = re.compile(rf"^{name}=(.*)$", re.MULTILINE)
        matches = list(pattern.finditer(content))
        if len(matches) > 1:
            raise ValueError(f"Duplicate {name} settings; remove duplicates first")
        if matches:
            if matches[0].group(1).strip().strip("\"'"):
                continue
            content = pattern.sub(f"{name}={value}", content)
        else:
            content = content.rstrip("\n") + f"\n{name}={value}\n"
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use localhost instead of Compose backend DNS",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    configure(root / ".env", local=args.local)
    print(
        "Browser configuration saved in .env; existing values preserved. Restart backend and workers."
    )
