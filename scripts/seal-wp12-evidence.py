#!/usr/bin/env python3
"""WP-12 evidence sealer (fail-closed).

Usage:
  seal-wp12-evidence.py --raw PATH --out PATH [--schema PATH]
                        [--allow-stub] [--require-official-sha]

Validates raw collect output has required inventory keys; writes sealed
manifest. Task EffectiveDone is NEVER claimed from inventory seal alone
(verify-done only). inventorySealed=true when v1 inventory is complete.
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
# Official WE client class used by WP-12A inventory runs.
OFFICIAL_APK_SHA256 = "6982c82745444c5f2eef5a3d8c89ad807360bb5849a133548a6b25d18f4c4cb0"
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


def _nonempty_dict(value: Any) -> bool:
    return isinstance(value, dict) and len(value) > 0


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def validate_v1_inventory_shapes(inventory: dict[str, Any]) -> list[str]:
    """Return list of shape errors for wp12a-manifest-map/v1 inventory fields.

    Accepts:
      - authorities: array (v1) or non-empty object (legacy scaffold)
      - permissions: object with declared/uses (v1) or non-empty object
      - dex / resources / manifest: objects with substantive content
    """
    errors: list[str] = []

    manifest = inventory.get("manifest")
    if not _nonempty_dict(manifest):
        errors.append("manifest must be non-empty object")

    dex = inventory.get("dex")
    if not isinstance(dex, dict):
        errors.append("dex must be object")
    elif not (dex.get("entries") or dex.get("count") is not None or len(dex) > 0):
        errors.append("dex must have entries/count or substantive keys")

    resources = inventory.get("resources")
    if not isinstance(resources, dict):
        errors.append("resources must be object")
    elif not (
        resources.get("entries") is not None
        or resources.get("arscSha256")
        or resources.get("idIndex") is not None
        or len(resources) > 0
    ):
        errors.append("resources must have entries/arscSha256/idIndex or substantive keys")

    authorities = inventory.get("authorities")
    if isinstance(authorities, list):
        if len(authorities) == 0:
            errors.append("authorities array is empty")
    elif isinstance(authorities, dict):
        if len(authorities) == 0:
            errors.append("authorities object is empty")
    else:
        errors.append("authorities must be array (v1) or object")

    permissions = inventory.get("permissions")
    if not isinstance(permissions, dict):
        errors.append("permissions must be object")
    else:
        # v1: declared/uses lists; also accept non-empty legacy maps
        has_declared = "declared" in permissions
        has_uses = "uses" in permissions
        if has_declared or has_uses:
            if has_declared and not isinstance(permissions.get("declared"), list):
                errors.append("permissions.declared must be list")
            if has_uses and not isinstance(permissions.get("uses"), list):
                errors.append("permissions.uses must be list")
            if has_declared and has_uses:
                if len(permissions.get("declared") or []) == 0 and len(permissions.get("uses") or []) == 0:
                    errors.append("permissions.declared and permissions.uses are both empty")
        elif len(permissions) == 0:
            errors.append("permissions object is empty")

    return errors


def inventory_is_complete(inventory: dict[str, Any], *, is_stub: bool) -> bool:
    if is_stub:
        return False
    missing = [k for k in REQUIRED_INVENTORY if k not in inventory]
    if missing:
        return False
    return len(validate_v1_inventory_shapes(inventory)) == 0


def slice_inventory_for_seal(inventory: dict[str, Any]) -> dict[str, Any]:
    """Preserve v1 shapes (authorities array; permissions declared/uses)."""
    authorities = inventory.get("authorities")
    if authorities is None:
        authorities = []
    permissions = inventory.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    return {
        "manifest": inventory.get("manifest") if isinstance(inventory.get("manifest"), dict) else {},
        "dex": inventory.get("dex") if isinstance(inventory.get("dex"), dict) else {},
        "resources": inventory.get("resources") if isinstance(inventory.get("resources"), dict) else {},
        "authorities": authorities,
        "permissions": permissions,
    }


def resolve_apk_sha(raw: dict[str, Any], inventory: dict[str, Any]) -> str | None:
    for candidate in (
        raw.get("officialApkSha256"),
        inventory.get("apkSha256"),
        (raw.get("hashes") or {}).get("officialApkSha256") if isinstance(raw.get("hashes"), dict) else None,
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="seal-wp12-evidence.py")
    parser.add_argument("--raw", required=True, help="raw collect JSON path")
    parser.add_argument("--out", required=True, help="sealed evidence output path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument(
        "--allow-stub",
        action="store_true",
        help="seal stub inventory for dry-run only (inventorySealed stays false)",
    )
    parser.add_argument(
        "--require-official-sha",
        action="store_true",
        help=f"fail-closed if apkSha256 present and != {OFFICIAL_APK_SHA256[:12]}…",
    )
    parser.add_argument(
        "--official-sha",
        default=OFFICIAL_APK_SHA256,
        help="expected official APK sha256 when --require-official-sha is set",
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

    shape_errors = validate_v1_inventory_shapes(inventory) if not is_stub else []
    if shape_errors and not is_stub:
        emit_failure(
            "INVENTORY_SHAPE_INVALID",
            "; ".join(shape_errors),
        )

    # failClosed.ok must not be false when present
    fail_closed = inventory.get("failClosed")
    if isinstance(fail_closed, dict) and fail_closed.get("ok") is False:
        emit_failure(
            "FAIL_CLOSED_NOT_OK",
            f"inventory.failClosed.ok is false: {fail_closed.get('failures')}",
        )

    apk_sha = resolve_apk_sha(raw, inventory)
    if args.require_official_sha:
        expected = (args.official_sha or OFFICIAL_APK_SHA256).lower()
        if apk_sha:
            if apk_sha.lower() != expected:
                emit_failure(
                    "WRONG_APK_CLASS",
                    f"apkSha256 {apk_sha} != official {expected}",
                )
        else:
            emit_failure(
                "MISSING_APK_SHA",
                " --require-official-sha needs officialApkSha256 or inventory.apkSha256",
            )

    inventory_sealed = inventory_is_complete(inventory, is_stub=is_stub)
    # Task EffectiveDone is verify-done only — never claimed from inventory seal.
    effective_done = False

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
        "inventory": slice_inventory_for_seal(inventory),
        "hashes": {
            "rawSha256": sha256_bytes(raw_bytes),
        },
        "failureSignature": raw.get("failureSignature"),
        "inventorySealed": inventory_sealed,
        "EffectiveDone": effective_done,
        "notes": [
            "Sealer: inventorySealed reflects complete non-stub v1 inventory.",
            "EffectiveDone is always false here; task EffectiveDone is verify-done only.",
        ],
    }
    if is_stub:
        sealed["notes"].append("sealed with --allow-stub; inventorySealed=false EffectiveDone=false")
    if apk_sha:
        sealed["hashes"]["officialApkSha256"] = apk_sha
    if inventory.get("schemaVersion"):
        sealed["inventorySchemaVersion"] = inventory.get("schemaVersion")
    if isinstance(fail_closed, dict):
        sealed["failClosed"] = {
            "ok": bool(fail_closed.get("ok")),
            "failureCount": len(fail_closed.get("failures") or []),
        }

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
        inventorySealed=inventory_sealed,
        EffectiveDone=effective_done,
        stub=is_stub,
        attemptNo=raw["attemptNo"],
        officialApkSha256=apk_sha,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
