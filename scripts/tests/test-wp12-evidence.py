#!/usr/bin/env python3
"""WP-12 evidence tooling tests (scaffold + RED outline).

At least one RED: missing inputs → non-zero exit + failureReason.
GREEN outline: init --local-only → status → assert-state TREE_FROZEN.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PLUGIN_ROOT / "scripts"
TXN_PY = SCRIPTS / "wp12-transaction.py"
COLLECT_PY = SCRIPTS / "collect-wp12-evidence.py"
SEAL_PY = SCRIPTS / "seal-wp12-evidence.py"
UPDATE_PY = SCRIPTS / "update-wp12-progress.py"
SCHEMA = PLUGIN_ROOT / "runtime-import" / "wp12-evidence.schema.json"
CONTRACT = PLUGIN_ROOT / "runtime-import" / "wp12-evidence-contract.json"


def run_py(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
        check=False,
    )


def parse_json_stdout(proc: subprocess.CompletedProcess[str]) -> dict:
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        raise AssertionError(f"empty stdout rc={proc.returncode} stderr={proc.stderr!r}")
    return json.loads(line[-1])


class TestScaffoldArtifacts(unittest.TestCase):
    def test_schema_and_contract_exist(self) -> None:
        self.assertTrue(SCHEMA.is_file(), f"missing {SCHEMA}")
        self.assertTrue(CONTRACT.is_file(), f"missing {CONTRACT}")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema.get("title"), "WP-12 sealed evidence manifest (scaffold)")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("runtime-inventory", contract.get("modes", {}))


class TestTransactionRedGreen(unittest.TestCase):
    def test_red_status_without_task_lists_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(TXN_PY, "status", "--transactions", tmp)
            self.assertEqual(proc.returncode, 0)
            payload = parse_json_stdout(proc)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("tasks"), [])

    def test_red_assert_state_missing_receipt(self) -> None:
        """RED outline: assert-state without init → MISSING_RECEIPT, non-zero."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(
                TXN_PY,
                "assert-state",
                "--task",
                "WP-12A",
                "--expected",
                "TREE_FROZEN",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = parse_json_stdout(proc)
            self.assertFalse(payload.get("ok"))
            self.assertEqual(payload.get("failureReason"), "MISSING_RECEIPT")

    def test_red_caller_supplied_identity_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(
                TXN_PY,
                "init",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
                "--local-only",
                "--transaction-id",
                "forged-id",
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = parse_json_stdout(proc)
            self.assertEqual(payload.get("failureReason"), "CALLER_SUPPLIED_IDENTITY")

    def test_red_require_bootstrap_pushed_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(
                TXN_PY,
                "init",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
                "--require-bootstrap-pushed",
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = parse_json_stdout(proc)
            self.assertEqual(payload.get("failureReason"), "BLOCKED_INFRA")

    def test_green_local_init_assert_tree_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init = run_py(
                TXN_PY,
                "init",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
                "--local-only",
                "--plugin-base-sha",
                "9968140147ff6f2471451cc270084bb8ae3a683e",
                "--mineradio-base-sha",
                "e00f8f87753a31070b40754223e2a216c5322827",
            )
            self.assertEqual(init.returncode, 0, msg=init.stdout + init.stderr)
            init_payload = parse_json_stdout(init)
            self.assertEqual(init_payload.get("state"), "TREE_FROZEN")
            self.assertFalse(init_payload.get("BOOTSTRAP_PUSHED"))

            status = run_py(TXN_PY, "status", "--task", "WP-12A", "--transactions", tmp)
            self.assertEqual(status.returncode, 0)
            status_payload = parse_json_stdout(status)
            self.assertEqual(status_payload.get("state"), "TREE_FROZEN")

            assert_st = run_py(
                TXN_PY,
                "assert-state",
                "--task",
                "WP-12A",
                "--expected",
                "TREE_FROZEN",
                "--transactions",
                tmp,
            )
            self.assertEqual(assert_st.returncode, 0, msg=assert_st.stdout + assert_st.stderr)

            # no-clobber second init
            again = run_py(
                TXN_PY,
                "init",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
                "--local-only",
            )
            self.assertNotEqual(again.returncode, 0)
            again_payload = parse_json_stdout(again)
            self.assertEqual(again_payload.get("failureReason"), "EVIDENCE_PATH_EXISTS")


class TestPhaseFences(unittest.TestCase):
    """Real RED→GREEN→REFACTOR→VERIFY phase fences (fail-closed)."""

    def _init_local(self, tmp: str) -> Path:
        proc = run_py(
            TXN_PY,
            "init",
            "--task",
            "WP-12A",
            "--transactions",
            tmp,
            "--local-only",
            "--plugin-base-sha",
            "9968140147ff6f2471451cc270084bb8ae3a683e",
            "--mineradio-base-sha",
            "e00f8f87753a31070b40754223e2a216c5322827",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertEqual(parse_json_stdout(proc).get("state"), "TREE_FROZEN")
        return Path(tmp) / "wp-12a.json"

    def test_record_red_advances_to_red_recorded(self) -> None:
        """init local → record-phase RED → state RED_RECORDED."""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_local(tmp)
            red = run_py(
                TXN_PY,
                "record-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--transactions",
                tmp,
            )
            self.assertEqual(red.returncode, 0, msg=red.stdout + red.stderr)
            payload = parse_json_stdout(red)
            self.assertEqual(payload.get("state"), "RED_RECORDED")
            self.assertFalse(payload.get("EffectiveDone"))

            receipt = json.loads((Path(tmp) / "wp-12a.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "RED_RECORDED")
            self.assertEqual(len(receipt.get("phaseEvents") or []), 1)
            event = receipt["phaseEvents"][0]
            self.assertEqual(event["phase"], "RED")
            self.assertNotEqual(event["exitCode"], 0)
            self.assertEqual(event["failureSignature"], "MISSING_DEX")
            self.assertEqual(event["stateAfter"], "RED_RECORDED")
            self.assertIn("stderrSha256", event)
            self.assertIn("stdoutSha256", event)
            self.assertIn("argv", event)
            self.assertIn("recordedAt", event)

    def test_full_red_green_refactor_verify_happy_path(self) -> None:
        """TREE_FROZEN → RED → GREEN → REFACTOR → VERIFIED."""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_local(tmp)
            expected_states = [
                ("RED", "RED_RECORDED"),
                ("GREEN", "GREEN_RECORDED"),
                ("REFACTOR", "REFACTOR_RECORDED"),
                ("VERIFY", "VERIFIED"),
            ]
            for phase, state in expected_states:
                proc = run_py(
                    TXN_PY,
                    "record-phase",
                    "--task",
                    "WP-12A",
                    "--phase",
                    phase,
                    "--transactions",
                    tmp,
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    msg=f"phase={phase} rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}",
                )
                payload = parse_json_stdout(proc)
                self.assertEqual(payload.get("state"), state, msg=f"phase={phase}")
                self.assertFalse(payload.get("EffectiveDone"))

            receipt = json.loads((Path(tmp) / "wp-12a.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "VERIFIED")
            self.assertFalse(receipt.get("EffectiveDone"))
            phases = [e["phase"] for e in receipt["phaseEvents"]]
            self.assertEqual(phases, ["RED", "GREEN", "REFACTOR", "VERIFY"])
            # RED non-zero + signature; others exit 0
            self.assertNotEqual(receipt["phaseEvents"][0]["exitCode"], 0)
            self.assertEqual(receipt["phaseEvents"][0]["failureSignature"], "MISSING_DEX")
            for event in receipt["phaseEvents"][1:]:
                self.assertEqual(event["exitCode"], 0)

            assert_st = run_py(
                TXN_PY,
                "assert-state",
                "--task",
                "WP-12A",
                "--expected",
                "VERIFIED",
                "--transactions",
                tmp,
            )
            self.assertEqual(assert_st.returncode, 0, msg=assert_st.stdout + assert_st.stderr)

    def test_out_of_order_phase_fails(self) -> None:
        """Skip/out-of-order phases refuse with OUT_OF_ORDER_PHASE."""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_local(tmp)
            # GREEN before RED
            green = run_py(
                TXN_PY,
                "record-phase",
                "--task",
                "WP-12A",
                "--phase",
                "GREEN",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(green.returncode, 0, msg=green.stdout + green.stderr)
            payload = parse_json_stdout(green)
            self.assertEqual(payload.get("failureReason"), "OUT_OF_ORDER_PHASE")

            # Still TREE_FROZEN
            status = run_py(TXN_PY, "status", "--task", "WP-12A", "--transactions", tmp)
            self.assertEqual(parse_json_stdout(status).get("state"), "TREE_FROZEN")

            # After RED, cannot jump to VERIFY
            red = run_py(
                TXN_PY,
                "record-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--transactions",
                tmp,
            )
            self.assertEqual(red.returncode, 0, msg=red.stdout + red.stderr)
            verify = run_py(
                TXN_PY,
                "record-phase",
                "--task",
                "WP-12A",
                "--phase",
                "VERIFY",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(verify.returncode, 0)
            self.assertEqual(parse_json_stdout(verify).get("failureReason"), "OUT_OF_ORDER_PHASE")

    def test_cannot_assert_done_unless_already_done(self) -> None:
        """Caller cannot assert DONE unless receipt already holds DONE+EffectiveDone."""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_local(tmp)
            # declare-done flag forbidden
            decl = run_py(
                TXN_PY,
                "assert-state",
                "--task",
                "WP-12A",
                "--expected",
                "TREE_FROZEN",
                "--declare-done",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(decl.returncode, 0)
            self.assertEqual(parse_json_stdout(decl).get("failureReason"), "CALLER_DECLARED_DONE")

            # expected DONE while state is TREE_FROZEN
            done = run_py(
                TXN_PY,
                "assert-state",
                "--task",
                "WP-12A",
                "--expected",
                "DONE",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(parse_json_stdout(done).get("failureReason"), "ILLEGAL_STATE")

            # phase command with --declare-done
            phase_decl = run_py(
                TXN_PY,
                "record-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--declare-done",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(phase_decl.returncode, 0)
            self.assertEqual(
                parse_json_stdout(phase_decl).get("failureReason"),
                "CALLER_DECLARED_DONE",
            )

    def test_phase_without_init_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(
                TXN_PY,
                "record-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(parse_json_stdout(proc).get("failureReason"), "MISSING_RECEIPT")

    def test_begin_run_complete_fence(self) -> None:
        """Explicit begin-phase / run-phase / complete-phase fence."""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_local(tmp)
            begin = run_py(
                TXN_PY,
                "begin-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--transactions",
                tmp,
            )
            self.assertEqual(begin.returncode, 0, msg=begin.stdout + begin.stderr)
            run = run_py(
                TXN_PY,
                "run-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--transactions",
                tmp,
            )
            self.assertEqual(run.returncode, 0, msg=run.stdout + run.stderr)
            run_payload = parse_json_stdout(run)
            self.assertNotEqual(run_payload.get("exitCode"), 0)
            self.assertEqual(run_payload.get("failureSignature"), "MISSING_DEX")
            # state not advanced until complete
            status = run_py(TXN_PY, "status", "--task", "WP-12A", "--transactions", tmp)
            self.assertEqual(parse_json_stdout(status).get("state"), "TREE_FROZEN")

            complete = run_py(
                TXN_PY,
                "complete-phase",
                "--task",
                "WP-12A",
                "--phase",
                "RED",
                "--transactions",
                tmp,
            )
            self.assertEqual(complete.returncode, 0, msg=complete.stdout + complete.stderr)
            self.assertEqual(parse_json_stdout(complete).get("state"), "RED_RECORDED")


class TestCollectSealRed(unittest.TestCase):
    def test_red_collect_missing_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw.json"
            proc = run_py(
                COLLECT_PY,
                "--mode",
                "runtime-inventory",
                "--out",
                str(out),
                "--attempt-no",
                "1",
                "--official-apk",
                str(Path(tmp) / "missing.apk"),
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = parse_json_stdout(proc)
            self.assertEqual(payload.get("failureReason"), "MISSING_INPUT")

    def test_red_seal_missing_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(
                SEAL_PY,
                "--raw",
                str(Path(tmp) / "nope.json"),
                "--out",
                str(Path(tmp) / "sealed.json"),
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = parse_json_stdout(proc)
            self.assertEqual(payload.get("failureReason"), "MISSING_INPUT")

    def test_red_update_progress_missing_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_py(
                UPDATE_PY,
                "--task",
                "WP-12A",
                "--sealed",
                str(Path(tmp) / "nope.json"),
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = parse_json_stdout(proc)
            self.assertEqual(payload.get("failureReason"), "MISSING_INPUT")

    def test_collect_seal_stub_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            txn_dir = Path(tmp) / "txns"
            init = run_py(
                TXN_PY,
                "init",
                "--task",
                "WP-12A",
                "--transactions",
                str(txn_dir),
                "--local-only",
            )
            self.assertEqual(init.returncode, 0, msg=init.stdout + init.stderr)
            txn_path = txn_dir / "wp-12a.json"
            apk = Path(tmp) / "fake.apk"
            apk.write_bytes(b"PK\x03\x04fake-apk-stub")

            raw_out = Path(tmp) / "raw.json"
            collect = run_py(
                COLLECT_PY,
                "--mode",
                "runtime-inventory",
                "--out",
                str(raw_out),
                "--transaction",
                str(txn_path),
                "--attempt-no",
                "1",
                "--official-apk",
                str(apk),
            )
            self.assertEqual(collect.returncode, 0, msg=collect.stdout + collect.stderr)

            sealed_out = Path(tmp) / "sealed.json"
            # without allow-stub → RED
            seal_red = run_py(SEAL_PY, "--raw", str(raw_out), "--out", str(sealed_out))
            self.assertNotEqual(seal_red.returncode, 0)
            self.assertEqual(parse_json_stdout(seal_red).get("failureReason"), "STUB_INVENTORY")

            seal_ok = run_py(
                SEAL_PY,
                "--raw",
                str(raw_out),
                "--out",
                str(sealed_out),
                "--allow-stub",
            )
            self.assertEqual(seal_ok.returncode, 0, msg=seal_ok.stdout + seal_ok.stderr)
            sealed_payload = parse_json_stdout(seal_ok)
            self.assertFalse(sealed_payload.get("EffectiveDone"))

            sealed = json.loads(sealed_out.read_text(encoding="utf-8"))
            self.assertFalse(sealed.get("EffectiveDone"))

            # progress update must refuse EffectiveDone=false
            prog = run_py(UPDATE_PY, "--task", "WP-12A", "--sealed", str(sealed_out))
            self.assertNotEqual(prog.returncode, 0)
            self.assertEqual(parse_json_stdout(prog).get("failureReason"), "EFFECTIVE_DONE_FALSE")


if __name__ == "__main__":
    unittest.main()
