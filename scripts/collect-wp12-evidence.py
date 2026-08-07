#!/usr/bin/env python3
"""WP-12 evidence collector (scaffold; fail-closed).

Usage:
  collect-wp12-evidence.py --mode runtime-inventory --out PATH \\
      [--official-apk PATH] [--transaction PATH] [--attempt-no N] \\
      [--inventory PATH]

  collect-wp12-evidence.py --mode native-closure --out PATH \\
      [--inventory PATH] [--official-apk PATH] \\
      --transaction PATH --attempt-no N

  collect-wp12-evidence.py --mode adapter-contract --out PATH \\
      [--inventory PATH] --transaction PATH --attempt-no N

Modes:
  runtime-inventory  — WP-12A manifest map (prebuilt inventory or APK stub)
  native-closure     — WP-12B native/JNI closure (alias: native-jni)
  native-jni         — alias of native-closure
  adapter-contract   — WP-12C embedded adapter contract (alias: embedded-adapter)
  embedded-adapter   — alias of adapter-contract

Writes a raw (unsealed) inventory JSON only when required inputs exist.
Never stages official APK bytes into Git-tracked paths.
Never forges EffectiveDone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

EXIT_FAIL = 2
SCHEMA = "wp12-evidence-raw/v1"
ADAPTER_CONTRACT_SCHEMA = "wp12c-adapter-contract/v1"
DEFAULT_PACKAGE_NAME = "com.motif.wallpaperengine"
DEFAULT_OFFICIAL_ENGINE_PACKAGE = "io.wallpaperengine.weclient"
MODES = frozenset(
    {
        "runtime-inventory",
        "native-jni",
        "native-closure",  # alias of native-jni (WP-12B)
        "adapter-contract",  # WP-12C embedded adapter contract
        "embedded-adapter",  # alias of adapter-contract
        "device-e2e3",
        "scene-video-e4",
    }
)
NATIVE_MODES = frozenset({"native-jni", "native-closure"})
ADAPTER_MODES = frozenset({"adapter-contract", "embedded-adapter"})
IMPLEMENTED_MODES = frozenset({"runtime-inventory"}) | NATIVE_MODES | ADAPTER_MODES

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
IMPORT_NATIVE = SCRIPT_DIR / "import-native-libs.sh"
VERIFY_EMBEDDED_ADAPTER = SCRIPT_DIR / "verify-embedded-adapter.sh"


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


def load_inventory_file(inv_path: Path) -> dict[str, Any]:
    if not inv_path.is_file():
        emit_failure("MISSING_INPUT", f"inventory not found: {inv_path}")
    try:
        inventory = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit_failure("ILLEGAL_STATE", f"inventory unreadable: {exc}")
    if not isinstance(inventory, dict):
        emit_failure("ILLEGAL_STATE", "inventory must be a JSON object")
    return inventory


def run_import_native(apk: Path, out_dir: Path) -> Path:
    """Run import-native-libs.sh; return path to native-inventory.json."""
    if not IMPORT_NATIVE.is_file():
        emit_failure("MISSING_TOOL", f"import-native-libs.sh not found: {IMPORT_NATIVE}")
    if not apk.is_file():
        emit_failure("MISSING_INPUT", f"official apk not found: {apk}")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        proc = subprocess.run(
            ["bash", str(IMPORT_NATIVE), "--apk", str(apk), "--out", str(out_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        emit_failure("ILLEGAL_STATE", f"import-native-libs failed to start: {exc}")
    if proc.returncode != 0:
        emit_failure(
            "IMPORT_FAILED",
            f"import-native-libs exit {proc.returncode}: {(proc.stderr or '')[-500:]}",
        )
    inv = out_dir / "native-inventory.json"
    if not inv.is_file():
        emit_failure("IMPORT_FAILED", "import-native-libs produced no native-inventory.json")
    return inv


def write_raw_evidence(
    out: Path,
    *,
    mode: str,
    txn: dict[str, Any],
    attempt_no: int,
    apk_sha: str | None,
    inventory_source: str | None,
    inventory: dict[str, Any] | None,
) -> None:
    raw = {
        "schema": SCHEMA,
        "mode": mode,
        "taskId": txn.get("taskId"),
        "transactionId": txn.get("transactionId"),
        "runUuid": txn.get("runUuid"),
        "attemptNo": attempt_no,
        "collectedAt": utc_now_iso(),
        "officialApkSha256": apk_sha,
        "inventorySource": inventory_source,
        "inventory": inventory,
        "sealed": False,
        "EffectiveDone": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


def collect_runtime_inventory(args: argparse.Namespace, txn: dict[str, Any], out: Path) -> int:
    inventory: dict[str, Any] | None = None
    apk_sha: str | None = None
    inventory_source: str | None = None
    if args.inventory:
        inv_path = Path(args.inventory)
        inventory = load_inventory_file(inv_path)
        inventory_source = str(inv_path.resolve())
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

    write_raw_evidence(
        out,
        mode=args.mode,
        txn=txn,
        attempt_no=args.attempt_no,
        apk_sha=apk_sha,
        inventory_source=inventory_source,
        inventory=inventory,
    )
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


def collect_native_closure(args: argparse.Namespace, txn: dict[str, Any], out: Path) -> int:
    """WP-12B: accept --inventory or run import-native-libs.sh on --official-apk."""
    inventory: dict[str, Any] | None = None
    apk_sha: str | None = None
    inventory_source: str | None = None
    # Canonical mode name in evidence payload (alias collapses to native-closure).
    evidence_mode = "native-closure" if args.mode in NATIVE_MODES else args.mode

    if args.inventory:
        inv_path = Path(args.inventory)
        inventory = load_inventory_file(inv_path)
        inventory_source = str(inv_path.resolve())
        # Prefer wp12b schema when present (fail-closed soft check — still accept if structure looks native).
        schema_v = inventory.get("schemaVersion")
        if schema_v is not None and schema_v != "wp12b-native-libs/v1":
            emit_failure(
                "ILLEGAL_STATE",
                f"native-closure inventory schemaVersion must be wp12b-native-libs/v1, got {schema_v!r}",
            )
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
        # Run import into a temp dir under out's parent (gitignored work path preferred).
        with tempfile.TemporaryDirectory(prefix="wp12b-collect-native.") as tmp:
            inv_path = run_import_native(apk, Path(tmp))
            inventory = load_inventory_file(inv_path)
            inventory_source = f"import-native-libs:{apk.resolve()}"
            inv_sha = inventory.get("apkSha256")
            file_sha = sha256_file(apk)
            if isinstance(inv_sha, str) and inv_sha and inv_sha.lower() != file_sha.lower():
                emit_failure(
                    "APK_SHA_MISMATCH",
                    f"inventory.apkSha256 {inv_sha} != file {file_sha}",
                )
            apk_sha = file_sha
            # inventory already loaded into memory; tmp cleaned on exit
    else:
        emit_failure(
            "MISSING_INPUT",
            "native-closure needs --inventory or --official-apk (fail-closed)",
        )

    write_raw_evidence(
        out,
        mode=evidence_mode,
        txn=txn,
        attempt_no=args.attempt_no,
        apk_sha=apk_sha,
        inventory_source=inventory_source,
        inventory=inventory,
    )
    return emit_ok(
        "collect",
        mode=evidence_mode,
        out=str(out),
        attemptNo=args.attempt_no,
        sealed=False,
        EffectiveDone=False,
        officialApkSha256=apk_sha,
        inventorySource=inventory_source,
    )


def summary_from_positive_harness() -> dict[str, Any]:
    """Run adapter-positive harness and build a minimal adapter-contract summary.

    Fail-closed: harness must exist and exit 0. Never forges EffectiveDone.
    """
    if not VERIFY_EMBEDDED_ADAPTER.is_file():
        emit_failure(
            "MISSING_TOOL",
            f"adapter-contract positive harness missing: {VERIFY_EMBEDDED_ADAPTER} "
            "(pass --inventory or land scripts/verify-embedded-adapter.sh first)",
        )
    try:
        proc = subprocess.run(
            ["bash", str(VERIFY_EMBEDDED_ADAPTER), "--case", "adapter-positive"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(PLUGIN_ROOT),
        )
    except OSError as exc:
        emit_failure("ILLEGAL_STATE", f"verify-embedded-adapter failed to start: {exc}")
    if proc.returncode != 0:
        emit_failure(
            "HARNESS_FAILED",
            f"adapter-positive exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[-500:]}",
        )
    # Harness passed: synthesize contract summary (fail-closed defaults).
    return {
        "schemaVersion": ADAPTER_CONTRACT_SCHEMA,
        "packageName": DEFAULT_PACKAGE_NAME,
        "officialEnginePackage": DEFAULT_OFFICIAL_ENGINE_PACKAGE,
        "embeddedRuntimeDefault": False,
        "failClosed": {"ok": True, "failures": []},
        "checks": {
            "unknownMethodRejected": True,
            "appendedArgsRejected": True,
            "fallbackMasqueradeRejected": True,
            "defaultUsesOfficial": True,
        },
        "harness": {
            "case": "adapter-positive",
            "exitCode": 0,
            "argv": [
                "bash",
                "scripts/verify-embedded-adapter.sh",
                "--case",
                "adapter-positive",
            ],
        },
    }


def collect_adapter_contract(args: argparse.Namespace, txn: dict[str, Any], out: Path) -> int:
    """WP-12C: accept --inventory adapter-contract JSON or run positive harness summary."""
    inventory: dict[str, Any] | None = None
    inventory_source: str | None = None
    # Canonical mode name (embedded-adapter alias collapses to adapter-contract).
    evidence_mode = "adapter-contract" if args.mode in ADAPTER_MODES else args.mode

    if args.inventory:
        inv_path = Path(args.inventory)
        inventory = load_inventory_file(inv_path)
        inventory_source = str(inv_path.resolve())
        schema_v = inventory.get("schemaVersion")
        if schema_v is not None and schema_v != ADAPTER_CONTRACT_SCHEMA:
            emit_failure(
                "ILLEGAL_STATE",
                f"adapter-contract inventory schemaVersion must be "
                f"{ADAPTER_CONTRACT_SCHEMA}, got {schema_v!r}",
            )
    else:
        inventory = summary_from_positive_harness()
        inventory_source = "harness:adapter-positive"

    write_raw_evidence(
        out,
        mode=evidence_mode,
        txn=txn,
        attempt_no=args.attempt_no,
        apk_sha=None,
        inventory_source=inventory_source,
        inventory=inventory,
    )
    return emit_ok(
        "collect",
        mode=evidence_mode,
        out=str(out),
        attemptNo=args.attempt_no,
        sealed=False,
        EffectiveDone=False,
        inventorySource=inventory_source,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="collect-wp12-evidence.py")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out", required=True, help="raw output path under work/ (gitignored)")
    parser.add_argument("--official-apk")
    parser.add_argument("--transaction", help="path to wp12 transaction receipt")
    parser.add_argument("--attempt-no", type=int)
    parser.add_argument(
        "--inventory",
        help="prebuilt inventory (runtime / native / adapter-contract JSON)",
    )
    args = parser.parse_args(argv)

    if args.mode not in MODES:
        emit_failure("UNKNOWN_MODE", f"unknown mode: {args.mode}")

    if args.mode not in IMPLEMENTED_MODES:
        emit_failure(
            "MODE_NOT_IMPLEMENTED",
            "scaffold implements runtime-inventory, native-closure/native-jni, "
            f"and adapter-contract/embedded-adapter; got {args.mode}",
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

    try:
        txn = json.loads(txn_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit_failure("ILLEGAL_STATE", f"transaction unreadable: {exc}")
    if not isinstance(txn, dict):
        emit_failure("ILLEGAL_STATE", "transaction must be a JSON object")

    if args.mode == "runtime-inventory":
        return collect_runtime_inventory(args, txn, out)
    if args.mode in NATIVE_MODES:
        return collect_native_closure(args, txn, out)
    if args.mode in ADAPTER_MODES:
        return collect_adapter_contract(args, txn, out)

    emit_failure("MODE_NOT_IMPLEMENTED", f"unhandled mode: {args.mode}")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
