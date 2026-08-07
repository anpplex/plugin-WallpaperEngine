#!/usr/bin/env python3
"""WP-12 transaction runner (Plugin worktree; scaffold).

State file under work/device-evidence/wp12/transactions/ (gitignored).
Fail-closed: no forged DONE, no caller-supplied transactionId/runUuid,
no BOOTSTRAP_PUSHED forgery.

Commands:
  init          Create exclusive transaction receipt → TREE_FROZEN (local)
  status        Print transaction state
  assert-state  Assert state == --expected (never forces DONE)

Serial barriers (subset; full machine expands later):
  TREE_FROZEN → RED_RECORDED → … → DONE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NoReturn

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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def emit_failure(reason: str, message: str = "", exit_code: int = EXIT_FAIL) -> NoReturn:
    payload = {"ok": False, "failureReason": reason, "message": message or reason}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    print(text, file=sys.stderr)
    print(text, file=sys.stdout)
    raise SystemExit(exit_code)


def fail(reason: str, message: str = "") -> NoReturn:
    emit_failure(reason, message)


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
        "phaseEvents": [],
        "attempts": [],
        "notes": [
            "Scaffold transaction. DONE/EffectiveDone only via verify-done after dual sync.",
        ],
    }


def cmd_init(args: argparse.Namespace) -> int:
    task_id = require_task(args.task)
    reject_caller_identity(args)
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


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "assert-state": cmd_assert_state,
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wp12-transaction.py")
    parser.add_argument("command", choices=sorted(COMMANDS.keys()))
    parser.add_argument("--task")
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
        fail("UNKNOWN_COMMAND", "missing command (init|status|assert-state)")
    args = parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
