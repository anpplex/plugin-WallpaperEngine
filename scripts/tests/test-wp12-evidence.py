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
