#!/usr/bin/env python3
"""WP-12 transaction runner (Plugin worktree).

State file under work/device-evidence/wp12/transactions/ (gitignored).
Fail-closed: no forged DONE, no caller-supplied transactionId/runUuid,
no BOOTSTRAP_PUSHED forgery, no phase skip / out-of-order advance.

Commands:
  init            Create exclusive transaction receipt → TREE_FROZEN (local)
  status          Print transaction state
  assert-state    Assert state == --expected (never forces DONE)
  begin-phase     Open a phase fence (RED|GREEN|REFACTOR|VERIFY)
  run-phase       Execute frozen catalog argv; write run receipt
  complete-phase  Advance state only if run receipt matches expectedExit policy
  record-phase    Convenience: begin + run + complete in one fence (still fail-closed)
  open-attempt    VERIFIED → EVIDENCE_ATTEMPT_OPEN (--attempt-no N)
  record-raw      EVIDENCE_ATTEMPT_OPEN → RAW_COLLECTED (--path raw.json)
  seal-evidence   RAW_COLLECTED → EVIDENCE_SEALED (--path sealed.json)
  prepare-plugin  VERIFIED|EVIDENCE_SEALED → PLUGIN_PREPARED (bookkeeping only)
  commit-plugin   PLUGIN_PREPARED → PLUGIN_COMMITTED (--commit-sha proven)
  record-plugin-merged  VERIFIED|EVIDENCE_SEALED|PLUGIN_PREPARED → PLUGIN_COMMITTED

Serial barriers (phase slice):
  TREE_FROZEN → RED_RECORDED → GREEN_RECORDED → REFACTOR_RECORDED → VERIFIED
Evidence slice:
  VERIFIED → EVIDENCE_ATTEMPT_OPEN → RAW_COLLECTED → EVIDENCE_SEALED
Plugin leg (dry-run bookkeeping; no auto git commit / no forged DONE):
  VERIFIED|EVIDENCE_SEALED → PLUGIN_PREPARED → PLUGIN_COMMITTED
  (DONE only via later dual-sync verify-done; never from caller.)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

EXIT_FAIL = 2
SCHEMA = "wp12-transaction/v1"
RECEIPT_MODE = 0o600

# Repo-relative default (Plugin worktree root = parent of scripts/)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TXN_DIR = PLUGIN_ROOT / "work" / "device-evidence" / "wp12" / "transactions"

KNOWN_TASKS = frozenset(
    {
        "WP-12A",
        "WP-12B",
        "WP-12C",
        "WP-12D",
        "WP-12E",
        "WP-12-BOOTSTRAP",
    }
)

LEGAL_STATES = frozenset(
    {
        "INIT",
        "TREE_FROZEN",
        "RED_RECORDED",
        "GREEN_RECORDED",
        "REFACTOR_RECORDED",
        "VERIFIED",
        "PLUGIN_PREPARED",
        "PLUGIN_COMMITTED",
        "EVIDENCE_ATTEMPT_OPEN",
        "RAW_COLLECTED",
        "EVIDENCE_SEALED",
        "EVIDENCE_PREPARED",
        "MINERADIO_EVIDENCE_COMMITTED",
        "PLUGIN_PUSHED",
        "MINERADIO_EVIDENCE_PUSHED",
        "CLOSURE_PREPARED",
        "MINERADIO_CLOSURE_COMMITTED",
        "MINERADIO_CLOSURE_PUSHED",
        "DONE",
        "FAILED",
        "BLOCKED_GIT_STATE",
        "BLOCKED_INFRA",
        "BLOCKED_EVIDENCE_STATE",
    }
)

# States a caller may assert; DONE only if receipt already holds it.
ASSERTABLE = LEGAL_STATES

# Phase fence definitions (ordered).
PHASES = ("RED", "GREEN", "REFACTOR", "VERIFY")
PHASE_TO_STATE = {
    "RED": "RED_RECORDED",
    "GREEN": "GREEN_RECORDED",
    "REFACTOR": "REFACTOR_RECORDED",
    "VERIFY": "VERIFIED",
}
PHASE_PREREQ = {
    "RED": "TREE_FROZEN",
    "GREEN": "RED_RECORDED",
    "REFACTOR": "GREEN_RECORDED",
    "VERIFY": "REFACTOR_RECORDED",
}

# Catalog-aligned frozen argv for WP-12A (plugin-root relative).
# Prefer hardcode over heavy catalog load; matches experimental catalog intent.
DEFAULT_PHASE_ARGV: dict[str, dict[str, list[str]]] = {
    "WP-12A": {
        "RED": [
            "bash",
            "scripts/verify-imported-runtime.sh",
            "--inventory",
            "scripts/tests/fixtures/manifest-missing-dex.json",
            "--mode",
            "negative-missing-dex",
        ],
        "GREEN": ["bash", "scripts/tests/test-runtime-import.sh"],
        "REFACTOR": ["true"],
        "VERIFY": ["bash", "scripts/tests/test-runtime-import.sh"],
    }
}

# RED expected stderr token / failureSignature (WP-12A primary catalog RED).
DEFAULT_RED_SIGNATURE: dict[str, str] = {
    "WP-12A": "MISSING_DEX",
}

# Plugin-leg allowlist paths that must exist at a recorded commit/tree (repo-relative).
# Matches WP-12A product files already on origin/main via PR #8/#9.
PLUGIN_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "WP-12A": (
        "runtime-import/wp12-evidence.schema.json",
        "runtime-import/wp12-evidence-contract.json",
        "scripts/wp12-transaction.py",
        "scripts/collect-wp12-evidence.py",
        "scripts/seal-wp12-evidence.py",
        "scripts/update-wp12-progress.py",
        "scripts/import-official-runtime.sh",
        "scripts/verify-imported-runtime.sh",
        "scripts/tests/test-wp12-evidence.py",
        "scripts/tests/test-runtime-import.sh",
    ),
}

# Commit subject allowlist for commit-plugin (prefix match, case-sensitive).
PLUGIN_COMMIT_SUBJECT_PREFIXES: tuple[str, ...] = (
    "feat(wp12a)",
    "feat(wp12)",
    "Merge pull request",  # already-merged PR tips (e.g. #8/#9)
)

PREPARE_PLUGIN_PREREQ = frozenset({"VERIFIED", "EVIDENCE_SEALED"})
COMMIT_PLUGIN_PREREQ = frozenset({"PLUGIN_PREPARED"})
RECORD_MERGED_PREREQ = frozenset({"VERIFIED", "EVIDENCE_SEALED", "PLUGIN_PREPARED"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def emit_failure(reason: str, message: str = "", exit_code: int = EXIT_FAIL, **extra: Any) -> NoReturn:
    payload = {"ok": False, "failureReason": reason, "message": message or reason, **extra}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    print(text, file=sys.stderr)
    print(text, file=sys.stdout)
    raise SystemExit(exit_code)


def fail(reason: str, message: str = "", **extra: Any) -> NoReturn:
    emit_failure(reason, message, **extra)


def emit_ok(command: str, **fields: Any) -> int:
    payload = {"ok": True, "command": command, **fields}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def reject_caller_identity(args: argparse.Namespace) -> None:
    if getattr(args, "transaction_id", None) or getattr(args, "run_uuid", None):
        fail(
            "CALLER_SUPPLIED_IDENTITY",
            "transactionId/runUuid must not be supplied on the CLI",
        )
    if os.environ.get("TRANSACTION_ID") or os.environ.get("RUN_UUID"):
        fail(
            "CALLER_SUPPLIED_IDENTITY",
            "transactionId/runUuid must not be supplied via environment",
        )


def require_task(task_id: str | None) -> str:
    if not task_id:
        fail("UNKNOWN_TASK", "missing --task")
    if task_id not in KNOWN_TASKS:
        fail("UNKNOWN_TASK", f"unknown task id: {task_id}")
    return task_id


def require_phase(phase: str | None) -> str:
    if not phase:
        fail("ILLEGAL_PHASE", "missing --phase")
    phase_u = phase.upper()
    if phase_u not in PHASES:
        fail("ILLEGAL_PHASE", f"unknown phase: {phase} (want one of {','.join(PHASES)})")
    return phase_u


def txn_dir(args: argparse.Namespace) -> Path:
    raw = args.transactions or str(DEFAULT_TXN_DIR)
    return Path(raw)


def transaction_path(directory: Path, task_id: str) -> Path:
    return directory / f"{task_id.lower()}.json"


def load_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail("MISSING_RECEIPT", f"receipt not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("ILLEGAL_STATE", f"receipt unreadable: {exc}")
    if not isinstance(data, dict):
        fail("ILLEGAL_STATE", "receipt must be a JSON object")
    return data


def atomic_write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, RECEIPT_MODE)
    except FileExistsError:
        fail("EVIDENCE_PATH_EXISTS", f"refusing to clobber existing path: {path}")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        raise


def atomic_write_replace(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically replace an existing receipt (or create if missing)."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, RECEIPT_MODE)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def empty_receipt(task_id: str, *, plugin_base: str | None, mineradio_base: str | None) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema": SCHEMA,
        "taskId": task_id,
        "state": "TREE_FROZEN",
        "revision": 1,
        "transactionId": str(uuid.uuid4()),
        "runUuid": str(uuid.uuid4()),
        "createdAt": now,
        "updatedAt": now,
        "EffectiveDone": False,
        "bootstrap": {
            "requiredState": "BOOTSTRAP_PUSHED",
            "observedBootstrapState": "SCAFFOLD_ONLY",
            "BOOTSTRAP_PUSHED": False,
            "note": "init under scaffold freezes local tree only; full WP-12A requires BOOTSTRAP_PUSHED",
        },
        "frozen": {
            "pluginBaseSha": plugin_base,
            "mineradioBaseSha": mineradio_base,
            "pluginWorktree": str(PLUGIN_ROOT),
            "txnRoot": str(DEFAULT_TXN_DIR),
        },
        "openPhase": None,
        "phaseEvents": [],
        "attempts": [],
        "notes": [
            "Scaffold transaction. DONE/EffectiveDone only via verify-done after dual sync.",
        ],
    }


def bump_receipt(receipt: dict[str, Any]) -> None:
    receipt["revision"] = int(receipt.get("revision") or 0) + 1
    receipt["updatedAt"] = utc_now_iso()
    # Never allow caller/path to forge EffectiveDone or DONE via phase tools.
    if receipt.get("state") != "DONE":
        receipt["EffectiveDone"] = False


def phase_argv_for(task_id: str, phase: str) -> list[str]:
    task_map = DEFAULT_PHASE_ARGV.get(task_id)
    if not task_map or phase not in task_map:
        fail(
            "NO_PHASE_ARGV",
            f"no frozen argv for task={task_id} phase={phase}",
        )
    return list(task_map[phase])


def red_signature_for(task_id: str) -> str:
    return DEFAULT_RED_SIGNATURE.get(task_id, "MISSING_DEX")


def ensure_not_declare_done(args: argparse.Namespace) -> None:
    if getattr(args, "declare_done", False):
        fail("CALLER_DECLARED_DONE", "caller must not declare DONE")
    # Refuse any attempt to assert/set DONE via phase commands.
    expected = getattr(args, "expected", None)
    if expected == "DONE":
        # assert-state handles DONE specially; phase cmds never accept DONE as phase.
        pass
    phase = getattr(args, "phase", None)
    if phase and str(phase).upper() == "DONE":
        fail("CALLER_DECLARED_DONE", "phase DONE is forbidden; use verify-done later")


def require_frozen_txn(path: Path) -> dict[str, Any]:
    """Load receipt; refuse if missing (must init --local-only first)."""
    receipt = load_receipt(path)
    state = receipt.get("state")
    if state is None:
        fail("ILLEGAL_STATE", "receipt missing state")
    if state == "DONE" or receipt.get("EffectiveDone") is True:
        # Phase tools never re-enter DONE; forbid forged DONE progression.
        fail(
            "ALREADY_DONE_OR_FORGED",
            "transaction already DONE/EffectiveDone; phase fences refuse re-entry",
            state=state,
        )
    return receipt


def validate_phase_prereq(receipt: dict[str, Any], phase: str) -> None:
    state = receipt.get("state")
    need = PHASE_PREREQ[phase]
    if state != need:
        # Distinguish skip vs wrong state.
        recorded = {e.get("phase") for e in (receipt.get("phaseEvents") or []) if isinstance(e, dict)}
        fail(
            "OUT_OF_ORDER_PHASE",
            f"phase {phase} requires state={need}, observed={state}; "
            f"recordedPhases={sorted(p for p in recorded if p)}",
            state=state,
            phase=phase,
            requiredState=need,
        )


def extract_failure_signature(stderr: str, phase: str, task_id: str) -> str | None:
    if phase != "RED":
        return None
    token = red_signature_for(task_id)
    # Match bare token as whole word / line (stderr prints MISSING_DEX alone).
    for line in stderr.splitlines():
        if line.strip() == token or token in line.split():
            return token
    if token in stderr:
        return token
    return None


def policy_ok(phase: str, exit_code: int, failure_signature: str | None, task_id: str) -> tuple[bool, str]:
    """Return (ok, reason) for complete-phase expectedExit policy."""
    if phase == "RED":
        expected_sig = red_signature_for(task_id)
        if exit_code == 0:
            return False, "RED_EXPECTED_NONZERO"
        if failure_signature != expected_sig:
            return False, f"RED_SIGNATURE_MISMATCH want={expected_sig} got={failure_signature}"
        return True, "ok"
    # GREEN / REFACTOR / VERIFY
    if exit_code != 0:
        return False, f"{phase}_EXPECTED_ZERO exit={exit_code}"
    return True, "ok"


def cmd_init(args: argparse.Namespace) -> int:
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)
    directory = txn_dir(args)
    path = transaction_path(directory, task_id)

    # Fail-closed: do not pretend infra bootstrap is pushed.
    if args.require_bootstrap_pushed:
        fail(
            "BLOCKED_INFRA",
            "BOOTSTRAP_PUSHED not verified (scaffold refuses require-bootstrap-pushed)",
        )

    plugin_base = args.plugin_base_sha
    mineradio_base = args.mineradio_base_sha
    if args.require_basesha and (not plugin_base or not mineradio_base):
        fail("MISSING_RECEIPT", "init --require-basesha needs both base SHAs")

    receipt = empty_receipt(task_id, plugin_base=plugin_base, mineradio_base=mineradio_base)
    if args.local_only:
        receipt["bootstrap"]["observedBootstrapState"] = "LOCAL_ONLY"
        receipt["notes"].append("init --local-only: TREE_FROZEN is local dry-run only")

    atomic_write_exclusive(path, receipt)
    return emit_ok(
        "init",
        taskId=task_id,
        state=receipt["state"],
        path=str(path),
        transactionId=receipt["transactionId"],
        runUuid=receipt["runUuid"],
        BOOTSTRAP_PUSHED=False,
        localOnly=bool(args.local_only),
    )


def cmd_status(args: argparse.Namespace) -> int:
    task_id = require_task(args.task) if args.task else None
    directory = txn_dir(args)
    if task_id:
        path = transaction_path(directory, task_id)
        if not path.is_file():
            return emit_ok(
                "status",
                taskId=task_id,
                exists=False,
                path=str(path),
                transactionsDir=str(directory),
                state=None,
            )
        receipt = load_receipt(path)
        return emit_ok(
            "status",
            taskId=task_id,
            exists=True,
            path=str(path),
            state=receipt.get("state"),
            revision=receipt.get("revision"),
            transactionId=receipt.get("transactionId"),
            runUuid=receipt.get("runUuid"),
            EffectiveDone=bool(receipt.get("EffectiveDone")),
            bootstrap=receipt.get("bootstrap"),
            frozen=receipt.get("frozen"),
            openPhase=receipt.get("openPhase"),
            openAttempt=receipt.get("openAttempt"),
            phaseEvents=receipt.get("phaseEvents") or [],
            attempts=receipt.get("attempts") or [],
            lastRaw=receipt.get("lastRaw"),
            lastSealed=receipt.get("lastSealed"),
            pluginPrepare=receipt.get("pluginPrepare"),
            pluginCommit=receipt.get("pluginCommit"),
            legs=receipt.get("legs"),
        )

    # Directory inventory
    if not directory.is_dir():
        return emit_ok(
            "status",
            exists=False,
            transactionsDir=str(directory),
            tasks=[],
        )
    tasks = []
    for p in sorted(directory.glob("wp-12*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tasks.append({"path": str(p), "error": "unreadable"})
            continue
        tasks.append(
            {
                "path": str(p),
                "taskId": data.get("taskId"),
                "state": data.get("state"),
                "revision": data.get("revision"),
            }
        )
    return emit_ok("status", transactionsDir=str(directory), tasks=tasks)


def cmd_assert_state(args: argparse.Namespace) -> int:
    task_id = require_task(args.task)
    if not args.expected:
        fail("ILLEGAL_STATE", "missing --expected")
    if args.expected not in ASSERTABLE:
        fail("ILLEGAL_STATE", f"unknown expected state: {args.expected}")
    if args.declare_done:
        fail("CALLER_DECLARED_DONE", "caller must not declare DONE")

    path = transaction_path(txn_dir(args), task_id)
    receipt = load_receipt(path)
    state = receipt.get("state")
    if state != args.expected:
        fail(
            "ILLEGAL_STATE",
            f"expected state={args.expected}, observed={state}",
        )
    if args.expected == "DONE" and receipt.get("EffectiveDone") is not True:
        # Even if state==DONE, EffectiveDone must be runner-derived (scaffold never sets it).
        fail("FORGED_EFFECTIVE_DONE", "state DONE without EffectiveDone=true")
    return emit_ok(
        "assert-state",
        taskId=task_id,
        state=state,
        path=str(path),
    )


def cmd_begin_phase(args: argparse.Namespace) -> int:
    task_id = require_task(args.task)
    phase = require_phase(args.phase)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    validate_phase_prereq(receipt, phase)

    open_phase = receipt.get("openPhase")
    if isinstance(open_phase, dict) and open_phase.get("phase"):
        if open_phase.get("phase") == phase and open_phase.get("run") is None:
            # Idempotent re-begin of same open (no run yet).
            return emit_ok(
                "begin-phase",
                taskId=task_id,
                phase=phase,
                state=receipt.get("state"),
                path=str(path),
                openPhase=open_phase,
                note="already open",
            )
        fail(
            "PHASE_ALREADY_OPEN",
            f"openPhase={open_phase.get('phase')} blocks begin-phase {phase}",
            openPhase=open_phase,
        )

    argv = phase_argv_for(task_id, phase)
    now = utc_now_iso()
    receipt["openPhase"] = {
        "phase": phase,
        "begunAt": now,
        "argv": argv,
        "run": None,
    }
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)
    return emit_ok(
        "begin-phase",
        taskId=task_id,
        phase=phase,
        state=receipt.get("state"),
        path=str(path),
        argv=argv,
        openPhase=receipt["openPhase"],
    )


def _execute_phase_argv(argv: Sequence[str]) -> dict[str, Any]:
    """Run argv with cwd=PLUGIN_ROOT; capture exit + hashes (not full bodies)."""
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(PLUGIN_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        fail("PHASE_EXEC_ERROR", f"failed to exec argv: {exc}", argv=list(argv))

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    return {
        "exitCode": int(proc.returncode),
        "stdoutSha256": sha256_text(stdout),
        "stderrSha256": sha256_text(stderr),
        "stdoutBytes": len(stdout.encode("utf-8", errors="replace")),
        "stderrBytes": len(stderr.encode("utf-8", errors="replace")),
        "stderrText": stderr,  # ephemeral for signature check; stripped before persist
        "stdoutText": stdout,
    }


def cmd_run_phase(args: argparse.Namespace) -> int:
    task_id = require_task(args.task)
    phase = require_phase(args.phase)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)

    open_phase = receipt.get("openPhase")
    if not isinstance(open_phase, dict) or open_phase.get("phase") != phase:
        fail(
            "PHASE_NOT_OPEN",
            f"run-phase {phase} requires matching openPhase (call begin-phase first)",
            openPhase=open_phase,
            state=receipt.get("state"),
        )
    # Still require correct prereq state (fail-closed if receipt was hand-edited).
    validate_phase_prereq(receipt, phase)

    argv = list(open_phase.get("argv") or phase_argv_for(task_id, phase))
    result = _execute_phase_argv(argv)
    failure_signature = extract_failure_signature(result["stderrText"], phase, task_id)

    # For RED, surface signature presence on run (complete-phase enforces policy).
    run_receipt = {
        "phase": phase,
        "argv": argv,
        "exitCode": result["exitCode"],
        "stdoutSha256": result["stdoutSha256"],
        "stderrSha256": result["stderrSha256"],
        "stdoutBytes": result["stdoutBytes"],
        "stderrBytes": result["stderrBytes"],
        "failureSignature": failure_signature,
        "ranAt": utc_now_iso(),
        "cwd": str(PLUGIN_ROOT),
    }
    open_phase["run"] = run_receipt
    receipt["openPhase"] = open_phase
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "run-phase",
        taskId=task_id,
        phase=phase,
        state=receipt.get("state"),
        path=str(path),
        exitCode=run_receipt["exitCode"],
        stdoutSha256=run_receipt["stdoutSha256"],
        stderrSha256=run_receipt["stderrSha256"],
        failureSignature=failure_signature,
        argv=argv,
    )


def cmd_complete_phase(args: argparse.Namespace) -> int:
    task_id = require_task(args.task)
    phase = require_phase(args.phase)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)

    open_phase = receipt.get("openPhase")
    if not isinstance(open_phase, dict) or open_phase.get("phase") != phase:
        fail(
            "PHASE_NOT_OPEN",
            f"complete-phase {phase} requires matching openPhase",
            openPhase=open_phase,
        )
    run = open_phase.get("run")
    if not isinstance(run, dict):
        fail("PHASE_NOT_RUN", f"complete-phase {phase} requires run-phase first")

    validate_phase_prereq(receipt, phase)

    exit_code = int(run.get("exitCode", -1))
    failure_signature = run.get("failureSignature")
    ok, reason = policy_ok(phase, exit_code, failure_signature, task_id)
    if not ok:
        fail(
            "PHASE_POLICY_FAILED",
            reason,
            phase=phase,
            exitCode=exit_code,
            failureSignature=failure_signature,
            state=receipt.get("state"),
        )

    state_after = PHASE_TO_STATE[phase]
    # Hard refuse advancing to DONE via phase machinery.
    if state_after == "DONE":
        fail("CALLER_DECLARED_DONE", "phase machinery must not set DONE")

    event = {
        "phase": phase,
        "argv": list(run.get("argv") or open_phase.get("argv") or []),
        "exitCode": exit_code,
        "stdoutSha256": run.get("stdoutSha256"),
        "stderrSha256": run.get("stderrSha256"),
        "failureSignature": failure_signature,
        "recordedAt": utc_now_iso(),
        "stateAfter": state_after,
        "ranAt": run.get("ranAt"),
        "cwd": run.get("cwd"),
    }
    events = list(receipt.get("phaseEvents") or [])
    events.append(event)
    receipt["phaseEvents"] = events
    receipt["state"] = state_after
    receipt["openPhase"] = None
    receipt["EffectiveDone"] = False  # never forge done from phase complete
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "complete-phase",
        taskId=task_id,
        phase=phase,
        state=state_after,
        path=str(path),
        phaseEvent=event,
        EffectiveDone=False,
    )


def cmd_record_phase(args: argparse.Namespace) -> int:
    """Convenience fence: begin + run + complete (still fail-closed).

    Local dry-run helper; does not skip policy or order checks.
    """
    task_id = require_task(args.task)
    phase = require_phase(args.phase)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    # begin
    begin_rc = cmd_begin_phase(args)
    if begin_rc != 0:
        return begin_rc
    # run
    run_rc = cmd_run_phase(args)
    if run_rc != 0:
        return run_rc
    # complete (advances state)
    complete_rc = cmd_complete_phase(args)
    if complete_rc != 0:
        return complete_rc

    path = transaction_path(txn_dir(args), task_id)
    receipt = load_receipt(path)
    events = receipt.get("phaseEvents") or []
    last = events[-1] if events else None
    return emit_ok(
        "record-phase",
        taskId=task_id,
        phase=phase,
        state=receipt.get("state"),
        path=str(path),
        phaseEvent=last,
        EffectiveDone=False,
        note="convenience begin+run+complete; fail-closed policy applied",
    )


def _require_evidence_path(path_str: str | None, label: str) -> Path:
    if not path_str:
        fail("MISSING_INPUT", f"missing --path for {label}")
    path = Path(path_str)
    if not path.is_file():
        fail("MISSING_INPUT", f"{label} path not found: {path}")
    return path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_open_attempt(args: argparse.Namespace) -> int:
    """VERIFIED → EVIDENCE_ATTEMPT_OPEN for a new evidence attempt."""
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    attempt_no = args.attempt_no
    if attempt_no is None or int(attempt_no) < 1:
        fail("MISSING_INPUT", "open-attempt requires --attempt-no >= 1")
    attempt_no = int(attempt_no)

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    state = receipt.get("state")
    if state != "VERIFIED":
        fail(
            "OUT_OF_ORDER_EVIDENCE",
            f"open-attempt requires state=VERIFIED, observed={state}",
            state=state,
        )

    attempts = list(receipt.get("attempts") or [])
    for existing in attempts:
        if isinstance(existing, dict) and int(existing.get("attemptNo") or 0) == attempt_no:
            fail(
                "ATTEMPT_EXISTS",
                f"attemptNo={attempt_no} already recorded",
                attemptNo=attempt_no,
            )

    now = utc_now_iso()
    attempt = {
        "attemptNo": attempt_no,
        "openedAt": now,
        "state": "EVIDENCE_ATTEMPT_OPEN",
        "rawPath": None,
        "rawSha256": None,
        "sealedPath": None,
        "sealedSha256": None,
        "inventorySealed": None,
        "EffectiveDone": False,
    }
    attempts.append(attempt)
    receipt["attempts"] = attempts
    receipt["openAttempt"] = {"attemptNo": attempt_no, "openedAt": now}
    receipt["state"] = "EVIDENCE_ATTEMPT_OPEN"
    receipt["EffectiveDone"] = False
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "open-attempt",
        taskId=task_id,
        state="EVIDENCE_ATTEMPT_OPEN",
        path=str(path),
        attemptNo=attempt_no,
        EffectiveDone=False,
    )


def cmd_record_raw(args: argparse.Namespace) -> int:
    """EVIDENCE_ATTEMPT_OPEN → RAW_COLLECTED after collect wrote raw evidence."""
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    raw_path = _require_evidence_path(args.path, "record-raw")
    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    state = receipt.get("state")
    if state != "EVIDENCE_ATTEMPT_OPEN":
        fail(
            "OUT_OF_ORDER_EVIDENCE",
            f"record-raw requires state=EVIDENCE_ATTEMPT_OPEN, observed={state}",
            state=state,
        )

    open_attempt = receipt.get("openAttempt")
    if not isinstance(open_attempt, dict) or open_attempt.get("attemptNo") is None:
        fail("ILLEGAL_STATE", "record-raw requires openAttempt on receipt")
    attempt_no = int(open_attempt["attemptNo"])

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("ILLEGAL_STATE", f"raw unreadable: {exc}")
    if not isinstance(raw, dict):
        fail("ILLEGAL_STATE", "raw must be a JSON object")

    # Identity must match transaction (fail-closed).
    if raw.get("transactionId") != receipt.get("transactionId"):
        fail(
            "IDENTITY_MISMATCH",
            "raw.transactionId does not match receipt",
        )
    if raw.get("runUuid") != receipt.get("runUuid"):
        fail("IDENTITY_MISMATCH", "raw.runUuid does not match receipt")
    if int(raw.get("attemptNo") or 0) != attempt_no:
        fail(
            "ATTEMPT_MISMATCH",
            f"raw.attemptNo={raw.get('attemptNo')} != open attemptNo={attempt_no}",
        )

    raw_sha = _sha256_file(raw_path)
    now = utc_now_iso()
    attempts = list(receipt.get("attempts") or [])
    found = False
    for entry in attempts:
        if isinstance(entry, dict) and int(entry.get("attemptNo") or 0) == attempt_no:
            entry["rawPath"] = str(raw_path.resolve())
            entry["rawSha256"] = raw_sha
            entry["rawRecordedAt"] = now
            entry["state"] = "RAW_COLLECTED"
            entry["officialApkSha256"] = raw.get("officialApkSha256")
            found = True
            break
    if not found:
        fail("ILLEGAL_STATE", f"open attemptNo={attempt_no} missing from attempts[]")

    receipt["attempts"] = attempts
    receipt["state"] = "RAW_COLLECTED"
    receipt["EffectiveDone"] = False
    receipt["lastRaw"] = {
        "attemptNo": attempt_no,
        "path": str(raw_path.resolve()),
        "sha256": raw_sha,
        "recordedAt": now,
    }
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "record-raw",
        taskId=task_id,
        state="RAW_COLLECTED",
        path=str(path),
        attemptNo=attempt_no,
        rawPath=str(raw_path.resolve()),
        rawSha256=raw_sha,
        EffectiveDone=False,
    )


def cmd_seal_evidence(args: argparse.Namespace) -> int:
    """RAW_COLLECTED → EVIDENCE_SEALED after sealer wrote sealed evidence.

    Does NOT set EffectiveDone=true (task EffectiveDone is verify-done only).
    Records inventorySealed from sealed JSON when present.
    """
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    sealed_path = _require_evidence_path(args.path, "seal-evidence")
    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    state = receipt.get("state")
    if state != "RAW_COLLECTED":
        fail(
            "OUT_OF_ORDER_EVIDENCE",
            f"seal-evidence requires state=RAW_COLLECTED, observed={state}",
            state=state,
        )

    open_attempt = receipt.get("openAttempt")
    if not isinstance(open_attempt, dict) or open_attempt.get("attemptNo") is None:
        fail("ILLEGAL_STATE", "seal-evidence requires openAttempt on receipt")
    attempt_no = int(open_attempt["attemptNo"])

    try:
        sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("ILLEGAL_STATE", f"sealed unreadable: {exc}")
    if not isinstance(sealed, dict):
        fail("ILLEGAL_STATE", "sealed must be a JSON object")

    if sealed.get("transactionId") != receipt.get("transactionId"):
        fail("IDENTITY_MISMATCH", "sealed.transactionId does not match receipt")
    if sealed.get("runUuid") != receipt.get("runUuid"):
        fail("IDENTITY_MISMATCH", "sealed.runUuid does not match receipt")
    if int(sealed.get("attemptNo") or 0) != attempt_no:
        fail(
            "ATTEMPT_MISMATCH",
            f"sealed.attemptNo={sealed.get('attemptNo')} != open attemptNo={attempt_no}",
        )
    # Refuse forged task EffectiveDone on seal attach.
    if sealed.get("EffectiveDone") is True:
        fail(
            "FORGED_EFFECTIVE_DONE",
            "sealed.EffectiveDone must be false; task EffectiveDone is verify-done only",
        )

    sealed_sha = _sha256_file(sealed_path)
    inventory_sealed = bool(sealed.get("inventorySealed"))
    now = utc_now_iso()
    attempts = list(receipt.get("attempts") or [])
    found = False
    for entry in attempts:
        if isinstance(entry, dict) and int(entry.get("attemptNo") or 0) == attempt_no:
            entry["sealedPath"] = str(sealed_path.resolve())
            entry["sealedSha256"] = sealed_sha
            entry["sealedAt"] = now
            entry["state"] = "EVIDENCE_SEALED"
            entry["inventorySealed"] = inventory_sealed
            entry["EffectiveDone"] = False
            found = True
            break
    if not found:
        fail("ILLEGAL_STATE", f"open attemptNo={attempt_no} missing from attempts[]")

    receipt["attempts"] = attempts
    receipt["state"] = "EVIDENCE_SEALED"
    receipt["EffectiveDone"] = False
    receipt["openAttempt"] = None
    receipt["lastSealed"] = {
        "attemptNo": attempt_no,
        "path": str(sealed_path.resolve()),
        "sha256": sealed_sha,
        "inventorySealed": inventory_sealed,
        "EffectiveDone": False,
        "recordedAt": now,
    }
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "seal-evidence",
        taskId=task_id,
        state="EVIDENCE_SEALED",
        path=str(path),
        attemptNo=attempt_no,
        sealedPath=str(sealed_path.resolve()),
        sealedSha256=sealed_sha,
        inventorySealed=inventory_sealed,
        EffectiveDone=False,
    )


# ---------------------------------------------------------------------------
# Plugin leg bookkeeping (dry-run only — records operator SHAs; no auto-commit)
# ---------------------------------------------------------------------------


def _git(
    *git_args: str,
    cwd: Path | None = None,
    timeout: float | None = 60.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *git_args],
            cwd=str(cwd or PLUGIN_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=["git", *git_args],
            returncode=124,
            stdout="",
            stderr=f"git timeout after {timeout}s: {' '.join(git_args)}",
        )


def _require_hex_sha(raw: str | None, *, label: str, lengths: tuple[int, ...] = (40,)) -> str:
    if not raw:
        fail("MISSING_INPUT", f"missing {label}")
    value = raw.strip().lower()
    if not all(c in "0123456789abcdef" for c in value):
        fail("INVALID_SHA", f"{label} must be lowercase hex, got {raw!r}")
    if len(value) not in lengths and not (7 <= len(value) <= 40):
        fail("INVALID_SHA", f"{label} must be 7-40 hex chars, got len={len(value)}")
    return value


def _resolve_git_object(spec: str, *, expect_type: str | None = None) -> tuple[str, str]:
    """Resolve rev to full 40-hex SHA and object type via git cat-file (fail-closed)."""
    proc = _git("cat-file", "-t", spec)
    if proc.returncode != 0:
        fail(
            "GIT_OBJECT_MISSING",
            f"git cat-file cannot resolve {spec!r}: {(proc.stderr or proc.stdout or '').strip()}",
            spec=spec,
        )
    obj_type = (proc.stdout or "").strip()
    if expect_type and obj_type != expect_type:
        fail(
            "GIT_OBJECT_TYPE_MISMATCH",
            f"expected {expect_type} for {spec!r}, got {obj_type}",
            spec=spec,
            objectType=obj_type,
        )
    full = _git("rev-parse", spec)
    if full.returncode != 0:
        fail("GIT_OBJECT_MISSING", f"git rev-parse failed for {spec!r}")
    sha = (full.stdout or "").strip().lower()
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        fail("INVALID_SHA", f"rev-parse returned non-40hex for {spec!r}: {sha!r}")
    return sha, obj_type


def _git_head_sha() -> str:
    sha, _ = _resolve_git_object("HEAD", expect_type="commit")
    return sha


def _git_commit_subject(commit_sha: str) -> str:
    proc = _git("log", "-1", "--format=%s", commit_sha)
    if proc.returncode != 0:
        fail("GIT_OBJECT_MISSING", f"cannot read subject for {commit_sha}")
    return (proc.stdout or "").strip()


def _subject_allowed(subject: str) -> bool:
    return any(subject.startswith(prefix) for prefix in PLUGIN_COMMIT_SUBJECT_PREFIXES)


def _is_ancestor_or_equal(ancestor: str, descendant: str) -> bool:
    if ancestor == descendant:
        return True
    proc = _git("merge-base", "--is-ancestor", ancestor, descendant)
    return proc.returncode == 0


def _allowlist_for(task_id: str) -> tuple[str, ...]:
    paths = PLUGIN_ALLOWLIST.get(task_id)
    if not paths:
        fail("NO_PLUGIN_ALLOWLIST", f"no plugin allowlist for task={task_id}")
    return paths


def _verify_allowlist_at(commit_or_tree: str, paths: Sequence[str]) -> list[str]:
    """Prove each allowlist path exists as a blob at commit/tree. Returns missing paths."""
    missing: list[str] = []
    for rel in paths:
        # Prefer commit:path via cat-file; works for both commit and tree^{}/path forms.
        # For a commit SHA, "SHA:path" resolves the blob.
        # For a tree SHA, use "SHA:path" as well (git allows tree:path).
        proc = _git("cat-file", "-e", f"{commit_or_tree}:{rel}")
        if proc.returncode != 0:
            missing.append(rel)
    return missing


def _ensure_legs(receipt: dict[str, Any]) -> dict[str, Any]:
    legs = receipt.get("legs")
    if not isinstance(legs, dict):
        legs = {}
    for key in ("plugin", "evidence", "closure"):
        if key not in legs or not isinstance(legs.get(key), dict):
            legs[key] = dict(legs.get(key) or {}) if isinstance(legs.get(key), dict) else {}
    receipt["legs"] = legs
    return legs


def cmd_prepare_plugin(args: argparse.Namespace) -> int:
    """Record prepared plugin tree identity only (no git commit).

    Requires VERIFIED or EVIDENCE_SEALED (tolerate evidence attach before plugin leg).
    Prefer operator --prepared-tree 40hex. Without it, verify allowlist paths exist
    at HEAD and record headSha (implementation already on origin/main via PR #8/#9).
    """
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    state = receipt.get("state")
    if state not in PREPARE_PLUGIN_PREREQ:
        fail(
            "OUT_OF_ORDER_PLUGIN",
            f"prepare-plugin requires state in {sorted(PREPARE_PLUGIN_PREREQ)}, observed={state}",
            state=state,
            requiredStates=sorted(PREPARE_PLUGIN_PREREQ),
        )

    allowlist = list(_allowlist_for(task_id))
    head_sha = _git_head_sha()
    prepared_tree_arg = getattr(args, "prepared_tree", None)
    note: str

    if prepared_tree_arg:
        raw_tree = _require_hex_sha(prepared_tree_arg, label="--prepared-tree", lengths=(40,))
        if len(raw_tree) != 40:
            # Resolve short form if operator passed abbreviated.
            tree_sha, _ = _resolve_git_object(raw_tree, expect_type="tree")
        else:
            tree_sha, _ = _resolve_git_object(raw_tree, expect_type="tree")
        missing = _verify_allowlist_at(tree_sha, allowlist)
        if missing:
            fail(
                "ALLOWLIST_MISSING",
                f"prepared-tree missing allowlist paths: {missing}",
                missing=missing,
                preparedTree=tree_sha,
            )
        note = "operator-supplied prepared-tree recorded; no git commit performed"
        mode = "prepared-tree"
    else:
        # Safer default for already-merged implementation: prove allowlist at HEAD.
        missing = _verify_allowlist_at(head_sha, allowlist)
        if missing:
            fail(
                "ALLOWLIST_MISSING",
                f"HEAD missing allowlist paths (pass --prepared-tree when staging): {missing}",
                missing=missing,
                headSha=head_sha,
            )
        # Record tree identity of HEAD without writing a new tree.
        tree_sha, _ = _resolve_git_object(f"{head_sha}^{{tree}}", expect_type="tree")
        note = (
            "implementation already on origin/main via PR #8/#9; "
            "recorded headSha/tree without git commit"
        )
        mode = "head-allowlist"

    now = utc_now_iso()
    prepare_record = {
        "preparedAt": now,
        "preparedTree": tree_sha,
        "headSha": head_sha,
        "allowlist": allowlist,
        "mode": mode,
        "note": note,
        "priorState": state,
    }
    receipt["pluginPrepare"] = prepare_record
    legs = _ensure_legs(receipt)
    legs["plugin"] = {
        **dict(legs.get("plugin") or {}),
        "preparedTree": tree_sha,
        "headSha": head_sha,
        "preparedAt": now,
        "state": "PLUGIN_PREPARED",
    }
    receipt["state"] = "PLUGIN_PREPARED"
    receipt["EffectiveDone"] = False
    notes = list(receipt.get("notes") or [])
    notes.append(f"prepare-plugin: {note}")
    receipt["notes"] = notes
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "prepare-plugin",
        taskId=task_id,
        state="PLUGIN_PREPARED",
        path=str(path),
        preparedTree=tree_sha,
        headSha=head_sha,
        mode=mode,
        note=note,
        EffectiveDone=False,
    )


def cmd_commit_plugin(args: argparse.Namespace) -> int:
    """Record operator-provided plugin commit SHA → PLUGIN_COMMITTED (no git commit).

    Requires PLUGIN_PREPARED. Proves commit exists, is ancestor of HEAD (or equals
    HEAD), and subject matches feat(wp12a)|feat(wp12)|Merge pull request.
    """
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    commit_raw = getattr(args, "commit_sha", None)
    if not commit_raw:
        fail("MISSING_INPUT", "commit-plugin requires --commit-sha")
    _require_hex_sha(commit_raw, label="--commit-sha")

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    state = receipt.get("state")
    if state not in COMMIT_PLUGIN_PREREQ:
        fail(
            "OUT_OF_ORDER_PLUGIN",
            f"commit-plugin requires state=PLUGIN_PREPARED, observed={state}",
            state=state,
        )

    commit_sha, _ = _resolve_git_object(commit_raw.strip().lower(), expect_type="commit")
    head_sha = _git_head_sha()
    if not _is_ancestor_or_equal(commit_sha, head_sha):
        fail(
            "COMMIT_NOT_ON_HEAD",
            f"commit {commit_sha} is not HEAD and not an ancestor of HEAD={head_sha}",
            commitSha=commit_sha,
            headSha=head_sha,
        )

    subject = _git_commit_subject(commit_sha)
    if not _subject_allowed(subject):
        fail(
            "COMMIT_SUBJECT_REJECTED",
            f"commit subject not in allowlist prefixes {list(PLUGIN_COMMIT_SUBJECT_PREFIXES)}: {subject!r}",
            subject=subject,
            commitSha=commit_sha,
        )

    allowlist = list(_allowlist_for(task_id))
    missing = _verify_allowlist_at(commit_sha, allowlist)
    if missing:
        fail(
            "ALLOWLIST_MISSING",
            f"commit missing allowlist paths: {missing}",
            missing=missing,
            commitSha=commit_sha,
        )

    tree_sha, _ = _resolve_git_object(f"{commit_sha}^{{tree}}", expect_type="tree")
    prepared = receipt.get("pluginPrepare") if isinstance(receipt.get("pluginPrepare"), dict) else {}
    prepared_tree = prepared.get("preparedTree")
    if prepared_tree and prepared_tree != tree_sha:
        # Soft note only when operator recorded a different prepared tree; still fail-closed
        # if allowlist paths at commit differ — already checked above. Tree mismatch is
        # informative for dry-run when HEAD advanced past prepare.
        pass

    now = utc_now_iso()
    commit_record = {
        "committedAt": now,
        "commitSha": commit_sha,
        "treeSha": tree_sha,
        "subject": subject,
        "headSha": head_sha,
        "allowlist": allowlist,
        "mode": "commit-sha",
        "note": "operator-supplied commit recorded; no git commit performed",
        "priorState": state,
    }
    receipt["pluginCommit"] = commit_record
    legs = _ensure_legs(receipt)
    legs["plugin"] = {
        **dict(legs.get("plugin") or {}),
        "commitSha": commit_sha,
        "treeSha": tree_sha,
        "subject": subject,
        "committedAt": now,
        "state": "PLUGIN_COMMITTED",
    }
    receipt["state"] = "PLUGIN_COMMITTED"
    receipt["EffectiveDone"] = False
    notes = list(receipt.get("notes") or [])
    notes.append(f"commit-plugin: recorded {commit_sha[:12]} subject={subject!r}")
    receipt["notes"] = notes
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "commit-plugin",
        taskId=task_id,
        state="PLUGIN_COMMITTED",
        path=str(path),
        commitSha=commit_sha,
        treeSha=tree_sha,
        subject=subject,
        EffectiveDone=False,
    )


def cmd_record_plugin_merged(args: argparse.Namespace) -> int:
    """Record already-merged plugin implementation → PLUGIN_COMMITTED.

    For local automation when code is already on origin/main (PR #8/#9).
    Requires VERIFIED|EVIDENCE_SEALED|PLUGIN_PREPARED. Proves merge-sha is a commit,
    allowlist paths exist at that commit, and (when origin/main is available) the
    merge is an ancestor of origin/main tip or equals it.
    """
    task_id = require_task(args.task)
    reject_caller_identity(args)
    ensure_not_declare_done(args)

    merge_raw = getattr(args, "merge_sha", None)
    if not merge_raw:
        fail("MISSING_INPUT", "record-plugin-merged requires --merge-sha")
    _require_hex_sha(merge_raw, label="--merge-sha")

    path = transaction_path(txn_dir(args), task_id)
    receipt = require_frozen_txn(path)
    state = receipt.get("state")
    if state not in RECORD_MERGED_PREREQ:
        fail(
            "OUT_OF_ORDER_PLUGIN",
            f"record-plugin-merged requires state in {sorted(RECORD_MERGED_PREREQ)}, observed={state}",
            state=state,
            requiredStates=sorted(RECORD_MERGED_PREREQ),
        )

    merge_sha, _ = _resolve_git_object(merge_raw.strip().lower(), expect_type="commit")
    allowlist = list(_allowlist_for(task_id))
    missing = _verify_allowlist_at(merge_sha, allowlist)
    if missing:
        fail(
            "ALLOWLIST_MISSING",
            f"merge-sha missing allowlist paths: {missing}",
            missing=missing,
            mergeSha=merge_sha,
        )

    # Prefer origin/main containment; fall back to local main / HEAD ancestry.
    main_tip: str | None = None
    main_source = None
    for ref in ("refs/remotes/origin/main", "origin/main", "refs/heads/main", "main"):
        proc = _git("rev-parse", "--verify", ref)
        if proc.returncode == 0:
            tip = (proc.stdout or "").strip().lower()
            if len(tip) == 40:
                main_tip = tip
                main_source = ref
                break

    if main_tip is not None:
        if not _is_ancestor_or_equal(merge_sha, main_tip):
            fail(
                "MERGE_NOT_ON_MAIN",
                f"merge-sha {merge_sha} is not contained in {main_source}={main_tip}",
                mergeSha=merge_sha,
                mainTip=main_tip,
                mainSource=main_source,
            )
    else:
        # No main ref — require merge is on current HEAD line.
        head_sha = _git_head_sha()
        if not _is_ancestor_or_equal(merge_sha, head_sha):
            fail(
                "MERGE_NOT_ON_HEAD",
                f"merge-sha {merge_sha} not on HEAD={head_sha} and origin/main unavailable",
                mergeSha=merge_sha,
                headSha=head_sha,
            )
        main_tip = head_sha
        main_source = "HEAD"

    # Optional ls-remote cross-check (skip/offline on timeout; fatal only when
    # ls-remote succeeds and returned tip does not contain merge-sha).
    ls = _git("ls-remote", "origin", "refs/heads/main", timeout=8.0)
    ls_remote_tip = None
    if ls.returncode == 0 and (ls.stdout or "").strip():
        first = (ls.stdout or "").splitlines()[0].split()
        if first and len(first[0]) == 40:
            ls_remote_tip = first[0].lower()
            if not _is_ancestor_or_equal(merge_sha, ls_remote_tip):
                fail(
                    "MERGE_NOT_ON_ORIGIN_MAIN",
                    f"ls-remote origin/main={ls_remote_tip} does not contain merge-sha {merge_sha}",
                    mergeSha=merge_sha,
                    originMain=ls_remote_tip,
                )

    subject = _git_commit_subject(merge_sha)
    tree_sha, _ = _resolve_git_object(f"{merge_sha}^{{tree}}", expect_type="tree")
    head_sha = _git_head_sha()
    now = utc_now_iso()
    note = (
        "implementation already merged on origin/main via PR #8/#9; "
        "recorded merge-sha without git commit"
    )
    # Auto-fill prepare if skipped (merged path may jump VERIFIED → PLUGIN_COMMITTED).
    if not isinstance(receipt.get("pluginPrepare"), dict):
        receipt["pluginPrepare"] = {
            "preparedAt": now,
            "preparedTree": tree_sha,
            "headSha": head_sha,
            "allowlist": allowlist,
            "mode": "record-plugin-merged-implicit",
            "note": "implicit prepare while recording merged implementation",
            "priorState": state,
        }

    commit_record = {
        "committedAt": now,
        "commitSha": merge_sha,
        "mergeSha": merge_sha,
        "treeSha": tree_sha,
        "subject": subject,
        "headSha": head_sha,
        "mainTip": main_tip,
        "mainSource": main_source,
        "lsRemoteMain": ls_remote_tip,
        "allowlist": allowlist,
        "mode": "record-plugin-merged",
        "note": note,
        "priorState": state,
    }
    receipt["pluginCommit"] = commit_record
    legs = _ensure_legs(receipt)
    legs["plugin"] = {
        **dict(legs.get("plugin") or {}),
        "commitSha": merge_sha,
        "mergeSha": merge_sha,
        "treeSha": tree_sha,
        "subject": subject,
        "committedAt": now,
        "state": "PLUGIN_COMMITTED",
        "mode": "record-plugin-merged",
    }
    receipt["state"] = "PLUGIN_COMMITTED"
    receipt["EffectiveDone"] = False
    notes = list(receipt.get("notes") or [])
    notes.append(f"record-plugin-merged: {merge_sha[:12]} via {main_source}")
    receipt["notes"] = notes
    bump_receipt(receipt)
    atomic_write_replace(path, receipt)

    return emit_ok(
        "record-plugin-merged",
        taskId=task_id,
        state="PLUGIN_COMMITTED",
        path=str(path),
        mergeSha=merge_sha,
        commitSha=merge_sha,
        treeSha=tree_sha,
        subject=subject,
        mainTip=main_tip,
        mainSource=main_source,
        lsRemoteMain=ls_remote_tip,
        note=note,
        EffectiveDone=False,
    )


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "assert-state": cmd_assert_state,
    "begin-phase": cmd_begin_phase,
    "run-phase": cmd_run_phase,
    "complete-phase": cmd_complete_phase,
    "record-phase": cmd_record_phase,
    "open-attempt": cmd_open_attempt,
    "record-raw": cmd_record_raw,
    "seal-evidence": cmd_seal_evidence,
    "prepare-plugin": cmd_prepare_plugin,
    "commit-plugin": cmd_commit_plugin,
    "record-plugin-merged": cmd_record_plugin_merged,
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wp12-transaction.py")
    parser.add_argument("command", choices=sorted(COMMANDS.keys()))
    parser.add_argument("--task")
    parser.add_argument("--phase", help="RED|GREEN|REFACTOR|VERIFY")
    parser.add_argument("--transactions", help="transactions directory (default: work/device-evidence/wp12/transactions)")
    parser.add_argument("--expected")
    parser.add_argument("--declare-done", action="store_true")
    parser.add_argument("--transaction-id", dest="transaction_id")
    parser.add_argument("--run-uuid", dest="run_uuid")
    parser.add_argument("--plugin-base-sha")
    parser.add_argument("--mineradio-base-sha")
    parser.add_argument("--require-basesha", action="store_true")
    parser.add_argument(
        "--require-bootstrap-pushed",
        action="store_true",
        help="fail-closed until real BOOTSTRAP_PUSHED (scaffold always fails this)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="mark init as local dry-run TREE_FROZEN (no push claim)",
    )
    parser.add_argument(
        "--attempt-no",
        type=int,
        help="evidence attempt number for open-attempt",
    )
    parser.add_argument(
        "--path",
        help="path to raw/sealed evidence JSON for record-raw / seal-evidence",
    )
    parser.add_argument(
        "--prepared-tree",
        dest="prepared_tree",
        help="operator-approved tree SHA (40 hex) for prepare-plugin; no git write-tree",
    )
    parser.add_argument(
        "--commit-sha",
        dest="commit_sha",
        help="existing commit SHA for commit-plugin bookkeeping (no git commit)",
    )
    parser.add_argument(
        "--merge-sha",
        dest="merge_sha",
        help="already-merged commit SHA for record-plugin-merged (e.g. origin/main tip)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    if not argv:
        fail(
            "UNKNOWN_COMMAND",
            "missing command (init|status|assert-state|begin-phase|run-phase|"
            "complete-phase|record-phase|open-attempt|record-raw|seal-evidence|"
            "prepare-plugin|commit-plugin|record-plugin-merged)",
        )
    args = parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
