#!/usr/bin/env python3
"""Set the Gemini API key across every env file that needs it.

Usage:
    python3 scripts/set-gemini-key.py <API_KEY>

Updates (creating the file from its .env.example if it doesn't exist yet):
    fello-frontend/.env.local   -> GEMINI_API_KEY
    fello-backend/backend/.env  -> GEMINI_API_KEY
    fello-agent/.env            -> GOOGLE_API_KEY (ADK's native Gemini var)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    (ROOT / "fello-frontend/.env.local", ROOT / "fello-frontend/.env.example", "GEMINI_API_KEY"),
    (ROOT / "fello-backend/backend/.env", ROOT / "fello-backend/backend/.env.example", "GEMINI_API_KEY"),
    (ROOT / "fello-agent/.env", ROOT / "fello-agent/.env.example", "GOOGLE_API_KEY"),
]


def upsert_var(path: Path, example_path: Path, var: str, value: str) -> str:
    if not path.exists():
        if example_path.exists():
            shutil.copy(example_path, path)
        else:
            path.touch()

    lines = path.read_text().splitlines()
    prefix = f"{var}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}"
            path.write_text("\n".join(lines) + "\n")
            return "updated"

    lines.append(f"{prefix}{value}")
    path.write_text("\n".join(lines) + "\n")
    return "appended"


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("Usage: python3 scripts/set-gemini-key.py <API_KEY>", file=sys.stderr)
        sys.exit(1)

    api_key = sys.argv[1].strip()

    for path, example_path, var in TARGETS:
        rel = path.relative_to(ROOT)
        try:
            action = upsert_var(path, example_path, var, api_key)
            print(f"[{action}] {rel} ({var})")
        except OSError as err:
            print(f"[failed] {rel}: {err}", file=sys.stderr)

    print("\nDone. Restart any running dev servers to pick up the new key.")


if __name__ == "__main__":
    main()
