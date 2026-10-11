#!/usr/bin/env python
"""Convert .env file to valid TOML format (e.g., for Streamlit secrets).

Usage:
  uv run python env_to_toml.py [--env-file .env] [--output env.toml]
"""

import argparse
from pathlib import Path


def parse_env(env_file: Path) -> dict:
    """Parse .env file into dict (skip comments, empty lines)."""
    env_vars = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            env_vars[key] = value
    return env_vars


def env_to_toml(env_vars: dict) -> str:
    """Convert env dict to TOML format."""
    lines = []
    for key, value in sorted(env_vars.items()):
        # TOML string: quote value, escape quotes inside
        escaped = value.replace('"', '\\"')
        lines.append(f'{key} = "{escaped}"')
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Convert .env to TOML (for Streamlit secrets)"
    )
    parser.add_argument("--env-file", default=".env", help=".env file path")
    parser.add_argument("--output", default="env.toml", help="Output TOML path")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if not env_file.exists():
        print(f"✗ {env_file} not found")
        return 1

    print(f"Reading {env_file}...")
    env_vars = parse_env(env_file)
    print(f"  {len(env_vars)} variables")

    toml = env_to_toml(env_vars)
    out_path = Path(args.output)
    out_path.write_text(toml)
    print(f"✓ Wrote {out_path}")
    print(f"\nUse this in Streamlit Cloud:")
    print(f"  Settings > Secrets > Paste entire content of {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
