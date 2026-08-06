#!/usr/bin/env python3
"""WP-12 evidence sealer (scaffold; fail-closed).

Usage:
  seal-wp12-evidence.py --raw PATH --out PATH [--schema PATH]

Validates raw collect output has required inventory keys; writes sealed
manifest with EffectiveDone only when inventory is complete and non-stub.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

EXIT_FAIL = 2
SEAL_SCHEMA = "wp12-evidence/v1"
REQUIRED_INVENTORY = ("manifest", "dex", "resources", "authorities", "permissions")
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = PLUGIN_ROOT / "runtime-import" / "wp12-evidence.schema.json"


def emit_failure(reason: str, message: str = "") -> NoReturn:
    payload = {"ok": False, "failureReason": reason, "message": message or reason}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    print(text, file=sys.stderr)
    print(text, file=sys.stdout)
    raise SystemExit(EXIT_FAIL)


def emit_ok(command: str, **fields: Any) -> int:
    print(json.dumps({"ok": True, "command": command, **fields}, ensure_ascii=False, separators=(",", ":")))
    return 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="seal-wp12-evidence.py")
    parser.add_argument("--raw", required=True, help="raw collect JSON path")
    parser.add_argument("--out", required=True, help="sealed evidence output path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument(
        "--allow-stub",
        action="store_true",
        help="seal stub inventory for dry-run only (EffectiveDone stays false)",
    )
    args = parser.parse_args(argv)

    raw_path = Path(args.raw)
    if not raw_path.is_file():
        emit_failure("MISSING_INPUT", f"raw evidence not found: {raw_path}")

    schema_path = Path(args.schema)
    if not schema_path.is_file():
        emit_failure("MISSING_INPUT", f"schema not found: {schema_path}")

    out = Path(args.out)
    if out.exists():
        emit_failure("EVIDENCE_PATH_EXISTS", f"refusing to clobber: {out}")

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit_failure("ILLEGAL_STATE", f"raw unreadable: {exc}")

    if not isinstance(raw, dict):
        emit_failure("ILLEGAL_STATE", "raw must be a JSON object")

    for key in ("mode", "transactionId", "runUuid", "attemptNo"):
        if raw.get(key) in (None, ""):
            emit_failure("MISSING_INPUT", f"raw missing field: {key}")

    inventory = raw.get("inventory")
    if not isinstance(inventory, dict):
        emit_failure("MISSING_INPUT", "raw.inventory missing or not object")

    missing_keys = [k for k in REQUIRED_INVENTORY if k not in inventory]
    if missing_keys:
        emit_failure(
            "INVENTORY_INCOMPLETE",
            f"inventory missing keys: {','.join(missing_keys)}",
        )

    is_stub = inventory.get("status") == "STUB_PENDING_IMPORT"
    if is_stub and not args.allow_stub:
        emit_failure(
            "STUB_INVENTORY",
            "refusing to seal STUB_PENDING_IMPORT without --allow-stub",
        )

    # EffectiveDone only when non-stub and inventory values are non-empty objects
    # with at least one substantive key each (scaffold bar).
    substantive = all(
        isinstance(inventory.get(k), dict) and len(inventory.get(k) or {}) > 0
        for k in REQUIRED_INVENTORY
    )
    effective_done = bool(substantive and not is_stub)

    raw_bytes = raw_path.read_bytes()
    sealed = {
        "schema": SEAL_SCHEMA,
        "taskId": raw.get("taskId") or "WP-12A",
        "mode": raw["mode"],
        "transactionId": raw["transactionId"],
        "runUuid": raw["runUuid"],
        "attemptNo": raw["attemptNo"],
        "sealedAt": utc_now_iso(),
        "pluginCommitSha": raw.get("pluginCommitSha"),
        "inventory": {
            "manifest": inventory.get("manifest") or {},
            "dex": inventory.get("dex") or {},
            "resources": inventory.get("resources") or {},
            "authorities": inventory.get("authorities") or {},
            "permissions": inventory.get("permissions") or {},
        },
        "hashes": {
            "rawSha256": sha256_bytes(raw_bytes),
        },
        "failureSignature": raw.get("failureSignature"),
        "EffectiveDone": effective_done,
        "notes": [
            "Scaffold sealer.",
            "EffectiveDone requires non-stub substantive inventory.",
        ],
    }
    if is_stub:
        sealed["notes"].append("sealed with --allow-stub; EffectiveDone=false")

    if raw.get("officialApkSha256"):
        sealed["hashes"]["officialApkSha256"] = raw["officialApkSha256"]

    payload = (json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    sealed["hashes"]["sealedManifestSha256"] = sha256_bytes(payload)
    # re-encode with final hash
    payload = (json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()

    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(out, flags, 0o600)
    except FileExistsError:
        emit_failure("EVIDENCE_PATH_EXISTS", f"refusing to clobber: {out}")
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())

    return emit_ok(
        "seal",
        out=str(out),
        EffectiveDone=effective_done,
        stub=is_stub,
        attemptNo=raw["attemptNo"],
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
