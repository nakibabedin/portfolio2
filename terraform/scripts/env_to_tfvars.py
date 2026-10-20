"""Turns a dotenv file (Railway's raw variable export) into
secrets.auto.tfvars.json, the `app_secrets` map Terraform stores in SSM.

    python scripts/env_to_tfvars.py path/to/railway.env

Prints only the variable names it kept and dropped, never a value. Run with
the backend's venv, which has python-dotenv:

    ..\\backend\\venv\\Scripts\\python.exe scripts\\env_to_tfvars.py railway.env
"""

import json
import sys
from pathlib import Path

from dotenv import dotenv_values

# Built by Terraform, replaced by the task role, frontend-only, or Railway's own.
DROPPED_EXACT = {
    "DATABASE_URL",
    "DATABASE_PUBLIC_URL",
    "PGPASSWORD",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "PORT",
}
DROPPED_PREFIXES = ("RAILWAY_", "NEXT_PUBLIC_", "NIXPACKS_")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    values = dotenv_values(sys.argv[1])

    kept, dropped = {}, []
    for key, value in values.items():
        if key in DROPPED_EXACT or key.startswith(DROPPED_PREFIXES) or value in (None, ""):
            dropped.append(key)
        else:
            kept[key] = value

    out = Path(__file__).resolve().parent.parent / "secrets.auto.tfvars.json"
    out.write_text(json.dumps({"app_secrets": kept}, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {out.name} with {len(kept)} variables:")
    for key in sorted(kept):
        print(f"  + {key}")
    if dropped:
        print("dropped (built by Terraform, replaced by the task role, or empty):")
        for key in sorted(dropped):
            print(f"  - {key}")


if __name__ == "__main__":
    main()
