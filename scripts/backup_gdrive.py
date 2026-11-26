# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Back up renders/ to Google Drive using Azure Key Vault (dp-kv-deliverypilot) configuration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERS_DIR = REPO_ROOT / "renders"
VAULT_NAME = "dp-kv-deliverypilot"
REMOTE_SECRET = "gdrive-backup-remote"
PROJECT_FOLDER = "session-1-sixth-form-college/renders"


def kv_get(secret_name: str) -> str:
    res = subprocess.run(
        [
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            VAULT_NAME,
            "--name",
            secret_name,
            "--query",
            "value",
            "-o",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def derive_dest_remote(example_remote: str) -> str:
    """Derive `<remote>:<base>/session-1-sixth-form-college/renders` from Vault's gdrive-backup-remote."""
    # Example in vault: gdrive-shared:secondbrain/backups/zulip -> gdrive-shared:secondbrain/backups
    if ":" not in example_remote:
        return f"gdrive-shared:secondbrain/backups/{PROJECT_FOLDER}"
    remote_name, path_part = example_remote.split(":", 1)
    parts = [p for p in path_part.strip("/").split("/") if p]
    base = "/".join(parts[:-1]) if len(parts) >= 2 else "/".join(parts)
    dest_path = f"{base}/{PROJECT_FOLDER}" if base else PROJECT_FOLDER
    return f"{remote_name}:{dest_path}"


def main() -> int:
    if not RENDERS_DIR.is_dir():
        print(f"ERROR: {RENDERS_DIR} does not exist.", file=sys.stderr)
        return 1

    print(f"Reading Google Drive backup remote from Azure Key Vault ({VAULT_NAME})...")
    vault_remote = kv_get(REMOTE_SECRET)
    dest = derive_dest_remote(vault_remote)
    print(f"Destination: {dest}")

    print(f"Uploading {RENDERS_DIR} -> {dest} ...")
    subprocess.run(
        [
            "rclone",
            "copy",
            str(RENDERS_DIR),
            dest,
            "--exclude",
            "*.html",
            "--exclude",
            "*.json",
            "--exclude",
            "*.txt",
            "--stats-one-line",
            "-v",
        ],
        check=True,
    )

    print("\n=== Verifying backed-up files on Google Drive ===")
    ls_res = subprocess.run(["rclone", "ls", dest], capture_output=True, text=True, check=True)
    print(ls_res.stdout.strip() or "(empty)")

    link_res = subprocess.run(["rclone", "link", dest], capture_output=True, text=True)
    if link_res.returncode == 0 and link_res.stdout.strip():
        print(f"\nGoogle Drive Link: {link_res.stdout.strip()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
