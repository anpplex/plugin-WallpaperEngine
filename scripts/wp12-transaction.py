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

Serial barriers (phase slice):
  TREE_FROZEN → RED_RECORDED → GREEN_RECORDED → REFACTOR_RECORDED → VERIFIED
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
            phaseEvents=receipt.get("phaseEvents") or [],
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


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "assert-state": cmd_assert_state,
    "begin-phase": cmd_begin_phase,
    "run-phase": cmd_run_phase,
    "complete-phase": cmd_complete_phase,
    "record-phase": cmd_record_phase,
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
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    if not argv:
        fail(
            "UNKNOWN_COMMAND",
            "missing command (init|status|assert-state|begin-phase|run-phase|complete-phase|record-phase)",
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
