#!/usr/bin/env python3
"""WP-12 evidence sealer (fail-closed).

Usage:
  seal-wp12-evidence.py --raw PATH --out PATH [--schema PATH]
                        [--allow-stub] [--require-official-sha]
                        [--official-sha HEX]

Validates raw collect output has required inventory keys; writes sealed
manifest. Task EffectiveDone is NEVER claimed from inventory seal alone
(verify-done only).

Supports:
  - WP-12A runtime-inventory (wp12a-manifest-map/v1): inventorySealed when
    manifest/dex/resources/authorities/permissions shapes are complete.
  - WP-12B native-closure / native-jni (schemaVersion startswith
    wp12b-native): inventorySealed when arm64-v8a has ≥1 lib, failClosed is
    ok (or legacy flags not triggered), and --require-official-sha matches
    when set. Does not require WP-12A inventory keys.
  - WP-12C adapter-contract (schemaVersion wp12c-adapter-contract/v1):
    inventorySealed when package isolation fields present, embeddedRuntimeDefault
    is false, failClosed ok, and checks reject unknown/appended/fallback.
    EffectiveDone stays false.
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
# Minimum keys for native-closure inventories (WP-12B).
REQUIRED_NATIVE_INVENTORY = (
    "schemaVersion",
    "packageName",
    "apkSha256",
    "abis",
    "failClosed",
)
# Minimum keys for adapter-contract inventories (WP-12C).
REQUIRED_ADAPTER_INVENTORY = (
    "schemaVersion",
    "packageName",
    "officialEnginePackage",
    "embeddedRuntimeDefault",
    "failClosed",
    "checks",
)
NATIVE_SCHEMA_PREFIX = "wp12b-native"
ADAPTER_SCHEMA_VERSION = "wp12c-adapter-contract/v1"
ADAPTER_SCHEMA_PREFIX = "wp12c-adapter-contract"
NATIVE_MODES = frozenset({"native-closure", "native-jni"})
ADAPTER_MODES = frozenset({"adapter-contract", "embedded-adapter"})
REQUIRED_ADAPTER_CHECKS = (
    "unknownMethodRejected",
    "appendedArgsRejected",
    "fallbackMasqueradeRejected",
    "defaultUsesOfficial",
)
# Official WE client class used by WP-12 inventory runs.
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


def is_native_mode(mode: str | None, inventory: dict[str, Any]) -> bool:
    """Detect WP-12B native-closure from raw.mode or inventory.schemaVersion."""
    if isinstance(mode, str) and mode in NATIVE_MODES:
        return True
    schema_v = inventory.get("schemaVersion")
    return isinstance(schema_v, str) and schema_v.startswith(NATIVE_SCHEMA_PREFIX)


def is_adapter_mode(mode: str | None, inventory: dict[str, Any]) -> bool:
    """Detect WP-12C adapter-contract from raw.mode or inventory.schemaVersion."""
    if isinstance(mode, str) and mode in ADAPTER_MODES:
        return True
    schema_v = inventory.get("schemaVersion")
    return isinstance(schema_v, str) and schema_v.startswith(ADAPTER_SCHEMA_PREFIX)


def arm64_lib_count(inventory: dict[str, Any]) -> int:
    abis = inventory.get("abis")
    if not isinstance(abis, list):
        return 0
    for row in abis:
        if not isinstance(row, dict):
            continue
        if row.get("name") == "arm64-v8a":
            libs = row.get("libs")
            return len(libs) if isinstance(libs, list) else 0
    return 0


def fail_closed_is_ok(fail_closed: Any) -> bool:
    """True when failClosed.ok is true, or legacy flags are not triggered."""
    if not isinstance(fail_closed, dict):
        return False
    if "ok" in fail_closed:
        return fail_closed.get("ok") is True
    # Legacy: structured trigger map (summary style) or failures list.
    if fail_closed.get("anyFailClosedTriggered") is True:
        return False
    failures = fail_closed.get("failures")
    if isinstance(failures, list) and len(failures) > 0:
        return False
    for key in (
        "MISSING_NEEDED",
        "WRONG_ABI",
        "DUPLICATE_SONAME",
        "EMPTY_ARM64",
        "EMPTY_NATIVE",
        "emptyArm64",
        "missingNeeded",
        "wrongAbi",
        "duplicateSoname",
    ):
        entry = fail_closed.get(key)
        if entry is True:
            return False
        if isinstance(entry, dict) and entry.get("triggered") is True:
            return False
    return True


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


def validate_native_inventory_shapes(inventory: dict[str, Any]) -> list[str]:
    """Return shape errors for required native inventory fields (not completeness)."""
    errors: list[str] = []

    schema_v = inventory.get("schemaVersion")
    if not isinstance(schema_v, str) or not schema_v.startswith(NATIVE_SCHEMA_PREFIX):
        errors.append(
            f"schemaVersion must start with {NATIVE_SCHEMA_PREFIX!r}, got {schema_v!r}"
        )

    package_name = inventory.get("packageName")
    if not isinstance(package_name, str) or not package_name.strip():
        errors.append("packageName must be non-empty string")

    apk_sha = inventory.get("apkSha256")
    if not isinstance(apk_sha, str) or not apk_sha.strip():
        errors.append("apkSha256 must be non-empty string")
    elif len(apk_sha) == 64 and any(c not in "0123456789abcdef" for c in apk_sha.lower()):
        errors.append("apkSha256 must be hex when 64 chars")

    abis = inventory.get("abis")
    if not isinstance(abis, list) or len(abis) == 0:
        errors.append("abis must be non-empty array")
    else:
        for i, row in enumerate(abis):
            if not isinstance(row, dict):
                errors.append(f"abis[{i}] must be object")
                continue
            name = row.get("name")
            libs = row.get("libs")
            if not isinstance(name, str) or not name:
                errors.append(f"abis[{i}].name missing")
            if not isinstance(libs, list):
                errors.append(f"abis[{i}].libs must be array")
                continue
            for j, lib in enumerate(libs):
                if not isinstance(lib, dict):
                    errors.append(f"abis[{i}].libs[{j}] must be object")
                    continue
                if not lib.get("name"):
                    errors.append(f"abis[{i}].libs[{j}].name missing")

    fail_closed = inventory.get("failClosed")
    if not isinstance(fail_closed, dict):
        errors.append("failClosed must be object")

    # Optional schema fields: validate type when present.
    jni = inventory.get("jniLoadLibs")
    if jni is not None and not isinstance(jni, list):
        errors.append("jniLoadLibs must be array when present")

    closure = inventory.get("closure")
    if closure is not None:
        if not isinstance(closure, dict):
            errors.append("closure must be object when present")
        else:
            for key in ("missingNeeded", "wrongAbi", "duplicateSoname", "systemNeeded"):
                if key in closure and not isinstance(closure.get(key), list):
                    errors.append(f"closure.{key} must be array")

    return errors


def validate_adapter_inventory_shapes(inventory: dict[str, Any]) -> list[str]:
    """Return shape errors for WP-12C adapter-contract inventory fields."""
    errors: list[str] = []

    schema_v = inventory.get("schemaVersion")
    if not isinstance(schema_v, str) or not schema_v.startswith(ADAPTER_SCHEMA_PREFIX):
        errors.append(
            f"schemaVersion must start with {ADAPTER_SCHEMA_PREFIX!r}, got {schema_v!r}"
        )
    elif schema_v != ADAPTER_SCHEMA_VERSION:
        # Accept only exact v1 for now (fail-closed on unknown future variants).
        errors.append(
            f"schemaVersion must be {ADAPTER_SCHEMA_VERSION!r}, got {schema_v!r}"
        )

    package_name = inventory.get("packageName")
    if not isinstance(package_name, str) or not package_name.strip():
        errors.append("packageName must be non-empty string")

    official = inventory.get("officialEnginePackage")
    if not isinstance(official, str) or not official.strip():
        errors.append("officialEnginePackage must be non-empty string")

    # Package isolation: plugin package must not equal official engine package.
    if (
        isinstance(package_name, str)
        and isinstance(official, str)
        and package_name.strip()
        and official.strip()
        and package_name.strip() == official.strip()
    ):
        errors.append("packageName must differ from officialEnginePackage (isolation)")

    emb_default = inventory.get("embeddedRuntimeDefault")
    if emb_default is not False:
        errors.append("embeddedRuntimeDefault must be false (fail-closed default official)")

    fail_closed = inventory.get("failClosed")
    if not isinstance(fail_closed, dict):
        errors.append("failClosed must be object")

    checks = inventory.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be object")
    else:
        for key in REQUIRED_ADAPTER_CHECKS:
            if key not in checks:
                errors.append(f"checks.{key} missing")
            elif checks.get(key) is not True:
                errors.append(f"checks.{key} must be true")

    return errors



def inventory_is_complete(
    inventory: dict[str, Any],
    *,
    is_stub: bool,
    native: bool,
    adapter: bool,
    require_official_sha: bool,
    expected_official_sha: str,
    apk_sha: str | None,
) -> bool:
    """inventorySealed criteria. EffectiveDone is never derived here."""
    if is_stub:
        return False
    if adapter:
        missing = [k for k in REQUIRED_ADAPTER_INVENTORY if k not in inventory]
        if missing:
            return False
        if validate_adapter_inventory_shapes(inventory):
            return False
        if not fail_closed_is_ok(inventory.get("failClosed")):
            return False
        if inventory.get("embeddedRuntimeDefault") is not False:
            return False
        return True
    if native:
        missing = [k for k in REQUIRED_NATIVE_INVENTORY if k not in inventory]
        if missing:
            return False
        if validate_native_inventory_shapes(inventory):
            return False
        if arm64_lib_count(inventory) < 1:
            return False
        if not fail_closed_is_ok(inventory.get("failClosed")):
            return False
        if require_official_sha:
            expected = (expected_official_sha or OFFICIAL_APK_SHA256).lower()
            if not apk_sha or apk_sha.lower() != expected:
                return False
        return True
    missing = [k for k in REQUIRED_INVENTORY if k not in inventory]
    if missing:
        return False
    return len(validate_v1_inventory_shapes(inventory)) == 0


def slice_inventory_for_seal(
    inventory: dict[str, Any],
    *,
    native: bool,
    adapter: bool,
) -> dict[str, Any]:
    """Preserve inventory shapes for sealed blob (no APK/SO bytes)."""
    if adapter:
        checks_in = inventory.get("checks") if isinstance(inventory.get("checks"), dict) else {}
        sliced_adapter: dict[str, Any] = {
            "schemaVersion": inventory.get("schemaVersion"),
            "packageName": inventory.get("packageName"),
            "officialEnginePackage": inventory.get("officialEnginePackage"),
            "embeddedRuntimeDefault": inventory.get("embeddedRuntimeDefault"),
            "failClosed": inventory.get("failClosed")
            if isinstance(inventory.get("failClosed"), dict)
            else {"ok": False, "failures": []},
            "checks": {
                key: bool(checks_in.get(key) is True) for key in REQUIRED_ADAPTER_CHECKS
            },
        }
        if isinstance(inventory.get("harness"), dict):
            sliced_adapter["harness"] = dict(inventory.get("harness") or {})
        return sliced_adapter

    if not native:
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

    abis_out: list[dict[str, Any]] = []
    total_so = 0
    for row in inventory.get("abis") or []:
        if not isinstance(row, dict):
            continue
        libs_out: list[dict[str, Any]] = []
        for lib in row.get("libs") or []:
            if not isinstance(lib, dict):
                continue
            entry = {
                "name": lib.get("name"),
                "path": lib.get("path"),
                "sha256": lib.get("sha256"),
                "sizeBytes": lib.get("sizeBytes"),
                "soname": lib.get("soname"),
                "needed": list(lib.get("needed") or []) if isinstance(lib.get("needed"), list) else [],
                "elfClass": lib.get("elfClass"),
                "elfMachine": lib.get("elfMachine"),
            }
            libs_out.append(entry)
            total_so += 1
        abis_out.append({"name": row.get("name"), "libs": libs_out, "libCount": len(libs_out)})

    closure_in = inventory.get("closure") if isinstance(inventory.get("closure"), dict) else {}
    sliced: dict[str, Any] = {
        "schemaVersion": inventory.get("schemaVersion"),
        "packageName": inventory.get("packageName"),
        "apkSha256": inventory.get("apkSha256"),
        "abis": abis_out,
        "failClosed": inventory.get("failClosed")
        if isinstance(inventory.get("failClosed"), dict)
        else {"ok": False, "failures": []},
        "counts": {
            "totalSo": total_so,
            "abiCount": len(abis_out),
            "arm64LibCount": next(
                (r["libCount"] for r in abis_out if r.get("name") == "arm64-v8a"),
                0,
            ),
        },
    }
    if inventory.get("versionCode") is not None:
        sliced["versionCode"] = inventory.get("versionCode")
    if inventory.get("versionName") is not None:
        sliced["versionName"] = inventory.get("versionName")
    if isinstance(inventory.get("jniLoadLibs"), list):
        sliced["jniLoadLibs"] = list(inventory.get("jniLoadLibs") or [])
        sliced["counts"]["jniLoadCount"] = len(sliced["jniLoadLibs"])
    if closure_in:
        sliced["closure"] = {
            "missingNeeded": list(closure_in.get("missingNeeded") or []),
            "wrongAbi": list(closure_in.get("wrongAbi") or []),
            "duplicateSoname": list(closure_in.get("duplicateSoname") or []),
            "systemNeeded": list(closure_in.get("systemNeeded") or []),
        }
    return sliced


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

    adapter = is_adapter_mode(raw.get("mode"), inventory)
    native = is_native_mode(raw.get("mode"), inventory) and not adapter
    if adapter and is_native_mode(raw.get("mode"), inventory):
        # Mode wins over schema ambiguity; adapter modes take precedence.
        native = False

    if adapter:
        missing_keys = [k for k in REQUIRED_ADAPTER_INVENTORY if k not in inventory]
        if missing_keys:
            emit_failure(
                "INVENTORY_INCOMPLETE",
                f"adapter-contract inventory missing keys: {','.join(missing_keys)}",
            )
    elif native:
        missing_keys = [k for k in REQUIRED_NATIVE_INVENTORY if k not in inventory]
        if missing_keys:
            emit_failure(
                "INVENTORY_INCOMPLETE",
                f"native inventory missing keys: {','.join(missing_keys)}",
            )
    else:
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

    if not is_stub:
        if adapter:
            shape_errors = validate_adapter_inventory_shapes(inventory)
        elif native:
            shape_errors = validate_native_inventory_shapes(inventory)
        else:
            shape_errors = validate_v1_inventory_shapes(inventory)
        if shape_errors:
            emit_failure(
                "INVENTORY_SHAPE_INVALID",
                "; ".join(shape_errors),
            )

    # failClosed.ok must not be false when present (v1 ok field).
    fail_closed = inventory.get("failClosed")
    if isinstance(fail_closed, dict) and fail_closed.get("ok") is False:
        emit_failure(
            "FAIL_CLOSED_NOT_OK",
            f"inventory.failClosed.ok is false: {fail_closed.get('failures')}",
        )

    apk_sha = resolve_apk_sha(raw, inventory)
    # Adapter-contract has no official APK sha requirement.
    if args.require_official_sha and not adapter:
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

    inventory_sealed = inventory_is_complete(
        inventory,
        is_stub=is_stub,
        native=native,
        adapter=adapter,
        require_official_sha=bool(args.require_official_sha) and not adapter,
        expected_official_sha=args.official_sha or OFFICIAL_APK_SHA256,
        apk_sha=apk_sha,
    )
    # Task EffectiveDone is verify-done only — never claimed from inventory seal.
    effective_done = False

    if adapter:
        default_task = "WP-12C"
    elif native:
        default_task = "WP-12B"
    else:
        default_task = "WP-12A"
    raw_bytes = raw_path.read_bytes()
    sealed = {
        "schema": SEAL_SCHEMA,
        "taskId": raw.get("taskId") or default_task,
        "mode": raw["mode"],
        "transactionId": raw["transactionId"],
        "runUuid": raw["runUuid"],
        "attemptNo": raw["attemptNo"],
        "sealedAt": utc_now_iso(),
        "pluginCommitSha": raw.get("pluginCommitSha"),
        "inventory": slice_inventory_for_seal(inventory, native=native, adapter=adapter),
        "hashes": {
            "rawSha256": sha256_bytes(raw_bytes),
        },
        "failureSignature": raw.get("failureSignature"),
        "inventorySealed": inventory_sealed,
        "EffectiveDone": effective_done,
        "notes": [
            "Sealer: inventorySealed reflects complete non-stub inventory for mode.",
            "EffectiveDone is always false here; task EffectiveDone is verify-done only.",
        ],
    }
    if adapter:
        sealed["notes"].append(
            "adapter-contract seal: package isolation + embeddedRuntimeDefault=false + "
            "failClosed ok + checks; EffectiveDone stays false."
        )
    if native:
        sealed["notes"].append(
            "native-closure seal: no WP-12A keys required; inventorySealed needs "
            "arm64-v8a libs + failClosed ok (+ official sha when required)."
        )
    if is_stub:
        sealed["notes"].append("sealed with --allow-stub; inventorySealed=false EffectiveDone=false")
    if apk_sha:
        sealed["hashes"]["officialApkSha256"] = apk_sha
    if inventory.get("schemaVersion"):
        sealed["inventorySchemaVersion"] = inventory.get("schemaVersion")
    if isinstance(fail_closed, dict):
        failures = fail_closed.get("failures")
        sealed["failClosed"] = {
            "ok": fail_closed_is_ok(fail_closed),
            "failureCount": len(failures) if isinstance(failures, list) else 0,
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
        native=native,
        adapter=adapter,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
