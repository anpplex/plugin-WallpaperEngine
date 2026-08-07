#!/usr/bin/env python3
"""WP-12 evidence collector (scaffold; fail-closed).

Usage:
  collect-wp12-evidence.py --mode runtime-inventory --out PATH \\
      [--official-apk PATH] [--transaction PATH] [--attempt-no N]

Writes a raw (unsealed) inventory JSON only when required inputs exist.
Never stages official APK bytes into Git-tracked paths.
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
SCHEMA = "wp12-evidence-raw/v1"
MODES = frozenset(
    {
        "runtime-inventory",
        "native-jni",
        "embedded-adapter",
        "device-e2e3",
        "scene-video-e4",
    }
)


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="collect-wp12-evidence.py")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out", required=True, help="raw output path under work/ (gitignored)")
    parser.add_argument("--official-apk")
    parser.add_argument("--transaction", help="path to wp12 transaction receipt")
    parser.add_argument("--attempt-no", type=int)
    parser.add_argument("--inventory", help="prebuilt inventory.json from import-official-runtime.sh")
    args = parser.parse_args(argv)

    if args.mode not in MODES:
        emit_failure("UNKNOWN_MODE", f"unknown mode: {args.mode}")

    if args.mode != "runtime-inventory":
        emit_failure(
            "MODE_NOT_IMPLEMENTED",
            f"scaffold only implements runtime-inventory; got {args.mode}",
        )

    # Fail-closed: transaction + attempt required for real collect path.
    if not args.transaction:
        emit_failure("MISSING_INPUT", "missing --transaction (fail-closed)")
    txn_path = Path(args.transaction)
    if not txn_path.is_file():
        emit_failure("MISSING_RECEIPT", f"transaction not found: {txn_path}")

    if args.attempt_no is None or args.attempt_no < 1:
        emit_failure("MISSING_INPUT", "missing or invalid --attempt-no")

    out = Path(args.out)
    if out.exists():
        emit_failure("EVIDENCE_PATH_EXISTS", f"refusing to clobber: {out}")

    # Prefer prebuilt inventory; else require official APK path existence (hash only).
    inventory: dict[str, Any] | None = None
    apk_sha: str | None = None
    inventory_source: str | None = None
    if args.inventory:
        inv_path = Path(args.inventory)
        if not inv_path.is_file():
            emit_failure("MISSING_INPUT", f"inventory not found: {inv_path}")
        try:
            inventory = json.loads(inv_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            emit_failure("ILLEGAL_STATE", f"inventory unreadable: {exc}")
        if not isinstance(inventory, dict):
            emit_failure("ILLEGAL_STATE", "inventory must be a JSON object")
        inventory_source = str(inv_path.resolve())
        # Copy apkSha256 from inventory into raw.officialApkSha256 (no APK bytes).
        inv_sha = inventory.get("apkSha256")
        if isinstance(inv_sha, str) and inv_sha:
            apk_sha = inv_sha
        if args.official_apk:
            apk = Path(args.official_apk)
            if apk.is_file():
                file_sha = sha256_file(apk)
                if apk_sha and file_sha.lower() != apk_sha.lower():
                    emit_failure(
                        "APK_SHA_MISMATCH",
                        f"inventory.apkSha256 {apk_sha} != file {file_sha}",
                    )
                if not apk_sha:
                    apk_sha = file_sha
    elif args.official_apk:
        apk = Path(args.official_apk)
        if not apk.is_file():
            emit_failure("MISSING_INPUT", f"official apk not found: {apk}")
        apk_sha = sha256_file(apk)
        # Scaffold: do not parse APK here (owned by import-official-runtime.sh).
        inventory = {
            "status": "STUB_PENDING_IMPORT",
            "note": "collect scaffold recorded apk sha256 only; run import-official-runtime.sh for full inventory",
            "manifest": {},
            "dex": {},
            "resources": {},
            "authorities": {},
            "permissions": {},
        }
        inventory_source = "stub-from-official-apk"
    else:
        emit_failure(
            "MISSING_INPUT",
            "need --inventory or --official-apk (fail-closed)",
        )

    try:
        txn = json.loads(txn_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit_failure("ILLEGAL_STATE", f"transaction unreadable: {exc}")

    raw = {
        "schema": SCHEMA,
        "mode": args.mode,
        "taskId": txn.get("taskId"),
        "transactionId": txn.get("transactionId"),
        "runUuid": txn.get("runUuid"),
        "attemptNo": args.attempt_no,
        "collectedAt": utc_now_iso(),
        "officialApkSha256": apk_sha,
        "inventorySource": inventory_source,
        "inventory": inventory,
        "sealed": False,
        "EffectiveDone": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # exclusive create
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    payload = (json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    try:
        fd = os.open(out, flags, 0o600)
    except FileExistsError:
        emit_failure("EVIDENCE_PATH_EXISTS", f"refusing to clobber: {out}")
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())

    return emit_ok(
        "collect",
        mode=args.mode,
        out=str(out),
        attemptNo=args.attempt_no,
        sealed=False,
        EffectiveDone=False,
        officialApkSha256=apk_sha,
        inventorySource=inventory_source,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
