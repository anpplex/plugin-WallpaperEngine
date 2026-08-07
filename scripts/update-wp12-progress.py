#!/usr/bin/env python3
"""WP-12 experimental progress updater (scaffold; fail-closed).

Refuses to write progress unless sealed evidence shows EffectiveDone=true
and the operator passes an explicit dual-repo closure proof path.

Scaffold never mutates WALLPAPER-PLUGIN-PROGRESS.zh-CN.md by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

EXIT_FAIL = 2
WEIGHTS = {
    "WP-12A": 25,
    "WP-12B": 25,
    "WP-12C": 20,
    "WP-12D": 15,
    "WP-12E": 15,
}


def emit_failure(reason: str, message: str = "") -> NoReturn:
    payload = {"ok": False, "failureReason": reason, "message": message or reason}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    print(text, file=sys.stderr)
    print(text, file=sys.stdout)
    raise SystemExit(EXIT_FAIL)


def emit_ok(command: str, **fields: Any) -> int:
    print(json.dumps({"ok": True, "command": command, **fields}, ensure_ascii=False, separators=(",", ":")))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="update-wp12-progress.py")
    parser.add_argument("--task", required=True)
    parser.add_argument("--sealed", required=True, help="sealed evidence JSON")
    parser.add_argument(
        "--closure-receipt",
        help="Mineradio closure receipt proving dual push (required to apply)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="default: dry-run only (scaffold always dry-runs)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="attempt real progress write (scaffold still fails without proofs)",
    )
    args = parser.parse_args(argv)

    if args.task not in WEIGHTS:
        emit_failure("UNKNOWN_TASK", f"unknown task: {args.task}")

    sealed_path = Path(args.sealed)
    if not sealed_path.is_file():
        emit_failure("MISSING_INPUT", f"sealed evidence not found: {sealed_path}")

    try:
        sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit_failure("ILLEGAL_STATE", f"sealed unreadable: {exc}")

    if sealed.get("EffectiveDone") is not True:
        emit_failure(
            "EFFECTIVE_DONE_FALSE",
            "refusing progress update while sealed EffectiveDone!=true",
        )

    if sealed.get("taskId") and sealed.get("taskId") != args.task:
        emit_failure(
            "TASK_MISMATCH",
            f"sealed taskId={sealed.get('taskId')} != --task {args.task}",
        )

    weight = WEIGHTS[args.task]

    if not args.apply:
        return emit_ok(
            "update-progress",
            dryRun=True,
            taskId=args.task,
            weightPercent=weight,
            applied=False,
            note="scaffold default dry-run; pass --apply with closure proof to write",
        )

    if not args.closure_receipt:
        emit_failure(
            "MISSING_INPUT",
            "--apply requires --closure-receipt (dual-repo closure proof)",
        )
    closure = Path(args.closure_receipt)
    if not closure.is_file():
        emit_failure("MISSING_INPUT", f"closure receipt not found: {closure}")

    # Scaffold: still refuse real mutation of progress docs.
    emit_failure(
        "SCAFFOLD_NO_APPLY",
        "scaffold refuses --apply; real progress write lands in bootstrap/closure green path",
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_failure("ILLEGAL_STATE", f"unhandled error: {exc}")
