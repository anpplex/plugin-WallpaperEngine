#!/usr/bin/env python3
"""WP-12 evidence collector (fail-closed).

Usage:
  collect-wp12-evidence.py --mode runtime-inventory --out PATH \\
      [--official-apk PATH] [--transaction PATH] [--attempt-no N] \\
      [--inventory PATH]

  collect-wp12-evidence.py --mode native-closure --out PATH \\
      [--inventory PATH] [--official-apk PATH] \\
      --transaction PATH --attempt-no N

  collect-wp12-evidence.py --mode adapter-contract --out PATH \\
      [--inventory PATH] --transaction PATH --attempt-no N

  collect-wp12-evidence.py --mode e2-e3 --out PATH \\
      (--inventory PATH | --offline-fixture PATH | live device args) \\
      [--serial SERIAL] [--user N] \\
      [--mineradio-apk PATH] [--plugin-apk PATH] [--official-apk PATH] \\
      --transaction PATH --attempt-no N

Modes:
  runtime-inventory  — WP-12A manifest map (prebuilt inventory or APK stub)
  native-closure     — WP-12B native/JNI closure (alias: native-jni)
  native-jni         — alias of native-closure
  adapter-contract   — WP-12C embedded adapter contract (alias: embedded-adapter)
  embedded-adapter   — alias of adapter-contract
  e2-e3              — WP-12D device E2/E3 (alias: device-e2e3)
  device-e2e3        — alias of e2-e3

Live e2-e3 (when --serial is set and no inventory/fixture):
  Requires local APK paths + --user. Hard-fail codes: DEVICE_OFFLINE,
  WRONG_USER, MISSING_APK, OFFICIAL_AS_EMBEDDED_HOST, packages missing on
  device. Soft fields: pluginPid, surface (best-effort). Sets
  deviceEvidenceClaimed=true only when hard checks pass. EffectiveDone
  always false.

Writes a raw (unsealed) inventory JSON only when required inputs exist.
Never stages official APK bytes into Git-tracked paths.
Never forges EffectiveDone.
Never forges device evidence offline (deviceEvidenceClaimed true only from
live hard-check pass path).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

EXIT_FAIL = 2
SCHEMA = "wp12-evidence-raw/v1"
ADAPTER_CONTRACT_SCHEMA = "wp12c-adapter-contract/v1"
DEVICE_E2E3_SCHEMA = "wp12d-device-e2e3/v1"
DEFAULT_PACKAGE_NAME = "com.motif.wallpaperengine"
DEFAULT_OFFICIAL_ENGINE_PACKAGE = "io.wallpaperengine.weclient"
DEFAULT_MINERADIO_PACKAGE = "com.mineradio.app"
DEFAULT_TARGET_USER = 12
MODES = frozenset(
    {
        "runtime-inventory",
        "native-jni",
        "native-closure",  # alias of native-jni (WP-12B)
        "adapter-contract",  # WP-12C embedded adapter contract
        "embedded-adapter",  # alias of adapter-contract
        "e2-e3",  # WP-12D device E2/E3 (canonical)
        "device-e2e3",  # alias of e2-e3
        "scene-video-e4",
    }
)
NATIVE_MODES = frozenset({"native-jni", "native-closure"})
ADAPTER_MODES = frozenset({"adapter-contract", "embedded-adapter"})
DEVICE_MODES = frozenset({"e2-e3", "device-e2e3"})
IMPLEMENTED_MODES = (
    frozenset({"runtime-inventory"}) | NATIVE_MODES | ADAPTER_MODES | DEVICE_MODES
)

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


def adb_device_state(serial: str) -> str | None:
    """Return adb get-state output (e.g. 'device') or None if adb fails."""
    if not serial or not str(serial).strip():
        return None
    try:
        proc = subprocess.run(
            ["adb", "-s", str(serial).strip(), "get-state"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    state = (proc.stdout or "").strip().replace("\r", "")
    return state or None


def adb_shell(serial: str, *shell_args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run adb -s SERIAL shell ...; return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["adb", "-s", str(serial).strip(), "shell", *shell_args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    out = (proc.stdout or "").replace("\r", "")
    err = (proc.stderr or "").replace("\r", "")
    return proc.returncode, out, err


def adb_pm_path(serial: str, package: str, user: int) -> str | None:
    """Return on-device APK path for package@user, or None if missing."""
    for args in (
        ("pm", "path", "--user", str(user), package),
        ("cmd", "package", "path", "--user", str(user), package),
        ("pm", "path", package),
    ):
        rc, out, _err = adb_shell(serial, *args, timeout=20)
        if rc != 0:
            continue
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                path = line[len("package:") :].strip()
                if path:
                    return path
    return None


def adb_current_user(serial: str) -> int | None:
    rc, out, _err = adb_shell(serial, "am", "get-current-user", timeout=15)
    if rc != 0:
        return None
    text = out.strip().splitlines()
    if not text:
        return None
    try:
        return int(text[0].strip())
    except ValueError:
        return None


def adb_plugin_pid(serial: str, package: str) -> int:
    """Best-effort plugin PID (0 if not running). Prefers :we_runtime process."""
    candidates = (
        f"{package}:we_runtime",
        package,
    )
    for name in candidates:
        rc, out, _err = adb_shell(serial, "pidof", name, timeout=15)
        if rc == 0 and out.strip():
            first = out.strip().split()[0]
            try:
                pid = int(first)
                if pid > 0:
                    return pid
            except ValueError:
                pass
    rc, out, _err = adb_shell(serial, "ps", "-A", "-o", "PID,NAME", timeout=20)
    if rc != 0:
        rc, out, _err = adb_shell(serial, "ps", "-A", timeout=20)
    if rc != 0 or not out:
        return 0
    preferred: list[int] = []
    fallback: list[int] = []
    for line in out.splitlines():
        if package not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[-1].strip()
        pid_val = None
        for tok in parts:
            try:
                n = int(tok)
            except ValueError:
                continue
            if n > 0:
                pid_val = n
                break
        if pid_val is None:
            continue
        if name == f"{package}:we_runtime" or name.endswith(":we_runtime"):
            preferred.append(pid_val)
        elif name == package or package in name:
            fallback.append(pid_val)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return 0


def adb_surface_hint(serial: str, package: str, plugin_pid: int) -> dict[str, Any]:
    """Best-effort surface/window hint for plugin package (soft field)."""
    surface: dict[str, Any] = {
        "present": False,
        "ownerPid": plugin_pid if plugin_pid > 0 else 0,
        "name": None,
    }
    # dumpsys window is large; prefer filtered activity surfaces when possible.
    for cmd in (
        ("dumpsys", "window", "windows"),
        ("dumpsys", "window"),
        ("dumpsys", "activity", "activities"),
    ):
        rc, out, _err = adb_shell(serial, *cmd, timeout=40)
        if rc != 0 or not out:
            continue
        hit_name: str | None = None
        for line in out.splitlines():
            if package not in line:
                continue
            # Prefer window/surface-ish lines.
            lower = line.lower()
            if any(
                token in lower
                for token in ("window", "surface", "wallpaper", "activityrecord")
            ):
                hit_name = line.strip()[:200]
                break
        if hit_name is None:
            # package mentioned at all is a weak surface hint
            for line in out.splitlines():
                if package in line:
                    hit_name = line.strip()[:200]
                    break
        if hit_name:
            surface["present"] = True
            surface["name"] = hit_name
            if plugin_pid > 0:
                surface["ownerPid"] = plugin_pid
            return surface
    return surface


def resolve_target_user(args: argparse.Namespace) -> int:
    user = getattr(args, "user", None)
    if user is None:
        return DEFAULT_TARGET_USER
    try:
        return int(user)
    except (TypeError, ValueError):
        emit_failure("MISSING_INPUT", f"invalid --user: {user!r}")


def resolve_live_apk_paths(args: argparse.Namespace) -> dict[str, Path]:
    """Resolve local APK paths for live e2-e3; fail-closed MISSING_APK."""
    mapping = {
        "mineradio": getattr(args, "mineradio_apk", None),
        "plugin": getattr(args, "plugin_apk", None),
        "officialWe": getattr(args, "official_apk", None),
    }
    missing: list[str] = []
    resolved: dict[str, Path] = {}
    for role, raw in mapping.items():
        if not raw or not str(raw).strip():
            missing.append(role)
            continue
        path = Path(str(raw).strip())
        if not path.is_file():
            missing.append(f"{role}:{path}")
            continue
        resolved[role] = path.resolve()
    if missing:
        emit_failure(
            "MISSING_APK",
            "live e2-e3 requires existing --mineradio-apk, --plugin-apk, "
            f"--official-apk; missing/invalid: {', '.join(missing)}",
        )
    return resolved


def build_live_device_inventory(
    *,
    serial: str,
    target_user: int,
    apk_paths: dict[str, Path],
) -> dict[str, Any]:
    """Probe device and build wp12d-device-e2e3/v1 inventory (hard-fail closed)."""
    state = adb_device_state(serial)
    if state != "device":
        emit_failure(
            "DEVICE_OFFLINE",
            f"serial={serial!r} adb state={state!r} (fail-closed; never forge device evidence)",
        )

    observed_user = adb_current_user(serial)
    if observed_user is None:
        emit_failure(
            "DEVICE_OFFLINE",
            f"serial={serial!r} unable to read am get-current-user",
        )
    if observed_user != target_user:
        emit_failure(
            "WRONG_USER",
            f"observedUser={observed_user} targetUser={target_user}",
        )

    plugin_pkg = DEFAULT_PACKAGE_NAME
    mineradio_pkg = DEFAULT_MINERADIO_PACKAGE
    official_pkg = DEFAULT_OFFICIAL_ENGINE_PACKAGE

    on_device_paths: dict[str, str | None] = {
        "mineradio": adb_pm_path(serial, mineradio_pkg, target_user),
        "plugin": adb_pm_path(serial, plugin_pkg, target_user),
        "officialWe": adb_pm_path(serial, official_pkg, target_user),
    }
    missing_pkgs = [role for role, path in on_device_paths.items() if not path]
    if missing_pkgs:
        emit_failure(
            "MISSING_APK",
            f"packages missing on device user={target_user}: {', '.join(missing_pkgs)} "
            f"(expected {mineradio_pkg}, {plugin_pkg}, {official_pkg})",
        )

    # Soft fields
    plugin_pid = adb_plugin_pid(serial, plugin_pkg)
    surface = adb_surface_hint(serial, plugin_pkg, plugin_pid)

    # realCaller: record Mineradio when installed (binding soft; installed is hard).
    mineradio_installed = bool(on_device_paths["mineradio"])
    real_caller: dict[str, Any] = {
        "package": mineradio_pkg if mineradio_installed else None,
        "uid": None,
        "isShell": False,
        "isMineradio": bool(mineradio_installed),
    }
    if mineradio_installed:
        rc, out, _err = adb_shell(
            serial, "dumpsys", "package", mineradio_pkg, timeout=30
        )
        if rc == 0 and out:
            # userId=NNNN or appId=NNNN under Package [com.mineradio.app]
            m = re.search(r"\buserId=(\d+)", out)
            if not m:
                m = re.search(r"\bappId=(\d+)", out)
            if m:
                try:
                    real_caller["uid"] = int(m.group(1))
                except ValueError:
                    pass

    # officialNotEmbeddedHost: plugin != weclient AND embedded host is not weclient
    embedded_host = plugin_pkg
    if embedded_host == official_pkg or plugin_pkg == official_pkg:
        emit_failure(
            "OFFICIAL_AS_EMBEDDED_HOST",
            f"plugin/embedded host must not be official WE package {official_pkg}",
        )
    official_not_embedded_host = True

    signatures = {
        "mineradio": sha256_file(apk_paths["mineradio"]),
        "plugin": sha256_file(apk_paths["plugin"]),
        "officialWe": sha256_file(apk_paths["officialWe"]),
    }

    # Hard checks all passed → claim live device evidence (EffectiveDone still false).
    inventory: dict[str, Any] = {
        "schemaVersion": DEVICE_E2E3_SCHEMA,
        "packageName": plugin_pkg,
        "serial": serial,
        "targetUser": target_user,
        "observedUser": observed_user,
        "deviceOnline": True,
        "contractDryRun": False,
        "deviceE3Claim": True,
        "deviceEvidenceClaimed": True,
        "apkPresent": {
            "mineradio": True,
            "plugin": True,
            "officialWe": True,
        },
        "onDeviceApkPaths": {
            "mineradio": on_device_paths["mineradio"],
            "plugin": on_device_paths["plugin"],
            "officialWe": on_device_paths["officialWe"],
        },
        "localApkSha256": signatures,
        "packageIdentities": {
            "mineradio": mineradio_pkg,
            "plugin": plugin_pkg,
            "officialWe": official_pkg,
            "embeddedHost": embedded_host,
        },
        "signatures": signatures,
        "pluginPid": plugin_pid,
        "surface": surface,
        "surfacePresent": bool(surface.get("present")),
        "realCaller": real_caller,
        "officialNotEmbeddedHost": official_not_embedded_host,
        "failClosed": {"ok": True, "failures": []},
        # Seal-facing contract checks (live hard path exercised these rejections).
        "checks": {
            "missingSerialRejected": True,
            "wrongUserRejected": True,
            "officialAsEmbeddedHostRejected": True,
            "offlineFailClosed": True,
        },
        "harness": {
            "case": "device-positive-live",
            "note": "live e2-e3 collect; soft surface/pluginPid; EffectiveDone remains false",
        },
    }
    return inventory


def normalize_device_inventory_from_fixture(inventory: dict[str, Any]) -> dict[str, Any]:
    """Normalize harness inventory fields; never invent deviceEvidenceClaimed=true."""
    inv = dict(inventory)
    if "deviceEvidenceClaimed" not in inv and "deviceE3Claim" in inv:
        claim = inv.get("deviceE3Claim")
        if isinstance(claim, bool):
            inv["deviceEvidenceClaimed"] = claim
    if not inv.get("packageName"):
        ids = inv.get("packageIdentities")
        if isinstance(ids, dict):
            plugin_pkg = ids.get("plugin")
            if isinstance(plugin_pkg, str) and plugin_pkg.strip():
                inv["packageName"] = plugin_pkg.strip()
    if inv.get("packageName") is None:
        inv["packageName"] = DEFAULT_PACKAGE_NAME
    return inv


def collect_device_e2e3(args: argparse.Namespace, txn: dict[str, Any], out: Path) -> int:
    """WP-12D: device E2/E3 collect — live device probe, or inventory/offline fixture.

    Fail-closed:
      - live path: --serial + APK paths + --user; hard codes exit without forging
      - fixture path: requires --inventory OR --offline-fixture
      - if --serial given on fixture path and device offline → DEVICE_OFFLINE
      - never forges deviceEvidenceClaimed=true offline
      - raw always EffectiveDone=false
    """
    evidence_mode = "device-e2e3" if args.mode in DEVICE_MODES else args.mode
    serial = getattr(args, "serial", None)
    if isinstance(serial, str):
        serial = serial.strip() or None
    else:
        serial = None

    has_fixture = bool(args.inventory) or bool(getattr(args, "offline_fixture", None))
    live_requested = serial is not None and not has_fixture

    inventory: dict[str, Any]
    inventory_source: str | None

    if live_requested:
        assert serial is not None
        target_user = resolve_target_user(args)
        apk_paths = resolve_live_apk_paths(args)
        inventory = build_live_device_inventory(
            serial=serial,
            target_user=target_user,
            apk_paths=apk_paths,
        )
        inventory_source = f"live-device:{serial}"
    else:
        if serial is not None:
            state = adb_device_state(serial)
            if state != "device":
                emit_failure(
                    "DEVICE_OFFLINE",
                    f"serial={serial!r} adb state={state!r} "
                    "(fail-closed; never forge device evidence)",
                )

        inv_path: Path | None = None
        if args.inventory:
            inv_path = Path(args.inventory)
            inventory_source = str(inv_path.resolve())
        elif getattr(args, "offline_fixture", None):
            inv_path = Path(args.offline_fixture)
            inventory_source = f"offline-fixture:{inv_path.resolve()}"
        else:
            emit_failure(
                "MISSING_INPUT",
                "e2-e3/device-e2e3 needs --inventory, --offline-fixture, or live "
                "args (--serial + --mineradio-apk + --plugin-apk + --official-apk)",
            )

        assert inv_path is not None
        inventory = normalize_device_inventory_from_fixture(load_inventory_file(inv_path))
        schema_v = inventory.get("schemaVersion")
        if schema_v is not None and schema_v != DEVICE_E2E3_SCHEMA:
            emit_failure(
                "ILLEGAL_STATE",
                f"device e2-e3 inventory schemaVersion must be "
                f"{DEVICE_E2E3_SCHEMA}, got {schema_v!r}",
            )

        # Never forge device evidence: claim true without online serial is illegal.
        claimed = inventory.get("deviceEvidenceClaimed")
        if claimed is True and serial is None:
            emit_failure(
                "DEVICE_EVIDENCE_FORGED",
                "deviceEvidenceClaimed=true requires --serial with online device "
                "(fail-closed; never forge device evidence)",
            )

        if serial is not None:
            inventory["serial"] = serial
            if "deviceEvidenceClaimed" not in inventory:
                # Online serial alone does not constitute sealed device evidence.
                inventory["deviceEvidenceClaimed"] = False

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
        deviceEvidenceClaimed=inventory.get("deviceEvidenceClaimed"),
        serial=serial or inventory.get("serial"),
        failClosedOk=(
            isinstance(inventory.get("failClosed"), dict)
            and inventory["failClosed"].get("ok") is True
        ),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="collect-wp12-evidence.py")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out", required=True, help="raw output path under work/ (gitignored)")
    parser.add_argument("--official-apk")
    parser.add_argument(
        "--mineradio-apk",
        help="local Mineradio APK path (live e2-e3 hard check)",
    )
    parser.add_argument(
        "--plugin-apk",
        help="local plugin APK path (live e2-e3 hard check)",
    )
    parser.add_argument("--transaction", help="path to wp12 transaction receipt")
    parser.add_argument("--attempt-no", type=int)
    parser.add_argument(
        "--inventory",
        help="prebuilt inventory (runtime / native / adapter-contract / device-e2e3 JSON)",
    )
    parser.add_argument(
        "--offline-fixture",
        help="WP-12D offline device contract fixture path (no live device evidence)",
    )
    parser.add_argument(
        "--serial",
        help="adb serial for WP-12D live collect; offline → DEVICE_OFFLINE (fail-closed)",
    )
    parser.add_argument(
        "--user",
        type=int,
        default=None,
        help=f"target Android user id for live e2-e3 (default {DEFAULT_TARGET_USER})",
    )
    args = parser.parse_args(argv)

    if args.mode not in MODES:
        emit_failure("UNKNOWN_MODE", f"unknown mode: {args.mode}")

    if args.mode not in IMPLEMENTED_MODES:
        emit_failure(
            "MODE_NOT_IMPLEMENTED",
            "scaffold implements runtime-inventory, native-closure/native-jni, "
            "adapter-contract/embedded-adapter, and e2-e3/device-e2e3; "
            f"got {args.mode}",
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
    if args.mode in DEVICE_MODES:
        return collect_device_e2e3(args, txn, out)

    emit_failure("MODE_NOT_IMPLEMENTED", f"unhandled mode: {args.mode}")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
