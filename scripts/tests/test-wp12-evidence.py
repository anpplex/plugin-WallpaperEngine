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
            self.assertFalse(sealed_payload.get("inventorySealed"))

            sealed = json.loads(sealed_out.read_text(encoding="utf-8"))
            self.assertFalse(sealed.get("EffectiveDone"))
            self.assertFalse(sealed.get("inventorySealed"))

            # progress update must refuse EffectiveDone=false
            prog = run_py(UPDATE_PY, "--task", "WP-12A", "--sealed", str(sealed_out))
            self.assertNotEqual(prog.returncode, 0)
            self.assertEqual(parse_json_stdout(prog).get("failureReason"), "EFFECTIVE_DONE_FALSE")

    def test_seal_v1_fixture_inventory_sealed_effective_done_false(self) -> None:
        """v1 inventory shapes → inventorySealed=true; EffectiveDone always false."""
        fixture = PLUGIN_ROOT / "scripts" / "tests" / "fixtures" / "manifest-inventory-pass.json"
        self.assertTrue(fixture.is_file(), f"missing fixture {fixture}")
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
                "--inventory",
                str(fixture),
            )
            self.assertEqual(collect.returncode, 0, msg=collect.stdout + collect.stderr)
            collect_payload = parse_json_stdout(collect)
            inv = json.loads(fixture.read_text(encoding="utf-8"))
            self.assertEqual(collect_payload.get("officialApkSha256"), inv.get("apkSha256"))
            raw = json.loads(raw_out.read_text(encoding="utf-8"))
            self.assertEqual(raw.get("officialApkSha256"), inv.get("apkSha256"))
            self.assertIsInstance(raw["inventory"]["authorities"], list)
            self.assertIsInstance(raw["inventory"]["permissions"], dict)
            self.assertIn("declared", raw["inventory"]["permissions"])

            sealed_out = Path(tmp) / "sealed.json"
            seal = run_py(SEAL_PY, "--raw", str(raw_out), "--out", str(sealed_out))
            self.assertEqual(seal.returncode, 0, msg=seal.stdout + seal.stderr)
            seal_payload = parse_json_stdout(seal)
            self.assertTrue(seal_payload.get("inventorySealed"))
            self.assertFalse(seal_payload.get("EffectiveDone"))

            sealed = json.loads(sealed_out.read_text(encoding="utf-8"))
            self.assertTrue(sealed.get("inventorySealed"))
            self.assertFalse(sealed.get("EffectiveDone"))
            self.assertIsInstance(sealed["inventory"]["authorities"], list)
            self.assertIn("declared", sealed["inventory"]["permissions"])
            self.assertEqual(
                sealed["hashes"].get("officialApkSha256"),
                inv.get("apkSha256"),
            )

            # Wrong APK class when --require-official-sha (fixture sha != official)
            wrong_out = Path(tmp) / "sealed-require.json"
            seal_req = run_py(
                SEAL_PY,
                "--raw",
                str(raw_out),
                "--out",
                str(wrong_out),
                "--require-official-sha",
            )
            self.assertNotEqual(seal_req.returncode, 0)
            self.assertEqual(parse_json_stdout(seal_req).get("failureReason"), "WRONG_APK_CLASS")


class TestEvidenceDag(unittest.TestCase):
    """VERIFIED → open-attempt → record-raw → seal-evidence."""

    def _init_and_verify(self, tmp: str) -> Path:
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
        for phase in ("RED", "GREEN", "REFACTOR", "VERIFY"):
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
            self.assertEqual(proc.returncode, 0, msg=f"{phase}: {proc.stdout}{proc.stderr}")
        status = run_py(TXN_PY, "status", "--task", "WP-12A", "--transactions", tmp)
        self.assertEqual(parse_json_stdout(status).get("state"), "VERIFIED")
        return Path(tmp) / "wp-12a.json"

    def test_evidence_slice_happy_path(self) -> None:
        fixture = PLUGIN_ROOT / "scripts" / "tests" / "fixtures" / "manifest-inventory-pass.json"
        with tempfile.TemporaryDirectory() as tmp:
            txn_path = self._init_and_verify(tmp)

            open_a = run_py(
                TXN_PY,
                "open-attempt",
                "--task",
                "WP-12A",
                "--attempt-no",
                "1",
                "--transactions",
                tmp,
            )
            self.assertEqual(open_a.returncode, 0, msg=open_a.stdout + open_a.stderr)
            self.assertEqual(parse_json_stdout(open_a).get("state"), "EVIDENCE_ATTEMPT_OPEN")

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
                "--inventory",
                str(fixture),
            )
            self.assertEqual(collect.returncode, 0, msg=collect.stdout + collect.stderr)

            rec = run_py(
                TXN_PY,
                "record-raw",
                "--task",
                "WP-12A",
                "--path",
                str(raw_out),
                "--transactions",
                tmp,
            )
            self.assertEqual(rec.returncode, 0, msg=rec.stdout + rec.stderr)
            self.assertEqual(parse_json_stdout(rec).get("state"), "RAW_COLLECTED")

            sealed_out = Path(tmp) / "sealed.json"
            seal = run_py(SEAL_PY, "--raw", str(raw_out), "--out", str(sealed_out))
            self.assertEqual(seal.returncode, 0, msg=seal.stdout + seal.stderr)
            self.assertTrue(parse_json_stdout(seal).get("inventorySealed"))
            self.assertFalse(parse_json_stdout(seal).get("EffectiveDone"))

            seal_txn = run_py(
                TXN_PY,
                "seal-evidence",
                "--task",
                "WP-12A",
                "--path",
                str(sealed_out),
                "--transactions",
                tmp,
            )
            self.assertEqual(seal_txn.returncode, 0, msg=seal_txn.stdout + seal_txn.stderr)
            payload = parse_json_stdout(seal_txn)
            self.assertEqual(payload.get("state"), "EVIDENCE_SEALED")
            self.assertTrue(payload.get("inventorySealed"))
            self.assertFalse(payload.get("EffectiveDone"))

            receipt = json.loads(txn_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "EVIDENCE_SEALED")
            self.assertFalse(receipt.get("EffectiveDone"))
            self.assertEqual(len(receipt.get("attempts") or []), 1)
            self.assertTrue(receipt["attempts"][0].get("inventorySealed"))

    def test_open_attempt_before_verified_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init = run_py(
                TXN_PY,
                "init",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
                "--local-only",
            )
            self.assertEqual(init.returncode, 0)
            open_a = run_py(
                TXN_PY,
                "open-attempt",
                "--task",
                "WP-12A",
                "--attempt-no",
                "1",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(open_a.returncode, 0)
            self.assertEqual(parse_json_stdout(open_a).get("failureReason"), "OUT_OF_ORDER_EVIDENCE")


class TestPluginLegBookkeeping(unittest.TestCase):
    """Plugin prepare/commit dry-run bookkeeping (no auto git commit, no DONE)."""

    # PR #9 merge on origin/main — already contains WP-12 allowlist paths.
    MERGED_SHA = "4255a9f16141818ba0beeab9bde1eddb0f862c31"
    FEAT_SHA = "e35250f1b5da38f685acabd5121698195dd683bb"

    def _init_local(self, tmp: str) -> Path:
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
        return Path(tmp) / "wp-12a.json"

    def _init_at_state(self, tmp: str, state: str) -> Path:
        """Init then stamp state for plugin-leg unit tests (skip slow phase argv)."""
        path = self._init_local(tmp)
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["state"] = state
        receipt["phaseEvents"] = [
            {"phase": "RED", "stateAfter": "RED_RECORDED"},
            {"phase": "GREEN", "stateAfter": "GREEN_RECORDED"},
            {"phase": "REFACTOR", "stateAfter": "REFACTOR_RECORDED"},
            {"phase": "VERIFY", "stateAfter": "VERIFIED"},
        ]
        receipt["EffectiveDone"] = False
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _init_and_verify(self, tmp: str) -> Path:
        """Real phase fences → VERIFIED (one integration path only)."""
        self._init_local(tmp)
        for phase in ("RED", "GREEN", "REFACTOR", "VERIFY"):
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
            self.assertEqual(proc.returncode, 0, msg=f"{phase}: {proc.stdout}{proc.stderr}")
        status = run_py(TXN_PY, "status", "--task", "WP-12A", "--transactions", tmp)
        self.assertEqual(parse_json_stdout(status).get("state"), "VERIFIED")
        return Path(tmp) / "wp-12a.json"

    def test_prepare_and_commit_plugin_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            txn_path = self._init_at_state(tmp, "VERIFIED")

            prep = run_py(
                TXN_PY,
                "prepare-plugin",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
            )
            self.assertEqual(prep.returncode, 0, msg=prep.stdout + prep.stderr)
            prep_payload = parse_json_stdout(prep)
            self.assertEqual(prep_payload.get("state"), "PLUGIN_PREPARED")
            self.assertFalse(prep_payload.get("EffectiveDone"))
            self.assertTrue(prep_payload.get("preparedTree"))
            self.assertTrue(prep_payload.get("headSha"))

            commit = run_py(
                TXN_PY,
                "commit-plugin",
                "--task",
                "WP-12A",
                "--commit-sha",
                self.FEAT_SHA,
                "--transactions",
                tmp,
            )
            self.assertEqual(commit.returncode, 0, msg=commit.stdout + commit.stderr)
            commit_payload = parse_json_stdout(commit)
            self.assertEqual(commit_payload.get("state"), "PLUGIN_COMMITTED")
            self.assertFalse(commit_payload.get("EffectiveDone"))
            self.assertEqual(commit_payload.get("commitSha"), self.FEAT_SHA)
            self.assertTrue(str(commit_payload.get("subject", "")).startswith("feat(wp12)"))

            receipt = json.loads(txn_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "PLUGIN_COMMITTED")
            self.assertFalse(receipt.get("EffectiveDone"))
            self.assertEqual(receipt["pluginCommit"]["commitSha"], self.FEAT_SHA)
            self.assertEqual(receipt["legs"]["plugin"]["state"], "PLUGIN_COMMITTED")

            # Cannot jump to DONE from PLUGIN_COMMITTED via assert
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

    def test_record_plugin_merged_from_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            txn_path = self._init_at_state(tmp, "VERIFIED")
            merged = run_py(
                TXN_PY,
                "record-plugin-merged",
                "--task",
                "WP-12A",
                "--merge-sha",
                self.MERGED_SHA,
                "--transactions",
                tmp,
            )
            self.assertEqual(merged.returncode, 0, msg=merged.stdout + merged.stderr)
            payload = parse_json_stdout(merged)
            self.assertEqual(payload.get("state"), "PLUGIN_COMMITTED")
            self.assertFalse(payload.get("EffectiveDone"))
            self.assertEqual(payload.get("mergeSha"), self.MERGED_SHA)
            self.assertIn("PR #8/#9", payload.get("note") or "")

            receipt = json.loads(txn_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "PLUGIN_COMMITTED")
            self.assertFalse(receipt.get("EffectiveDone"))
            self.assertEqual(receipt["pluginCommit"]["mode"], "record-plugin-merged")
            self.assertIsNotNone(receipt.get("pluginPrepare"))

    def test_prepare_plugin_with_prepared_tree(self) -> None:
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=str(PLUGIN_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(tree.returncode, 0, msg=tree.stderr)
        tree_sha = tree.stdout.strip()
        with tempfile.TemporaryDirectory() as tmp:
            self._init_at_state(tmp, "VERIFIED")
            prep = run_py(
                TXN_PY,
                "prepare-plugin",
                "--task",
                "WP-12A",
                "--prepared-tree",
                tree_sha,
                "--transactions",
                tmp,
            )
            self.assertEqual(prep.returncode, 0, msg=prep.stdout + prep.stderr)
            payload = parse_json_stdout(prep)
            self.assertEqual(payload.get("state"), "PLUGIN_PREPARED")
            self.assertEqual(payload.get("preparedTree"), tree_sha)
            self.assertEqual(payload.get("mode"), "prepared-tree")
            self.assertFalse(payload.get("EffectiveDone"))

    def test_out_of_order_prepare_plugin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._init_local(tmp)
            prep = run_py(
                TXN_PY,
                "prepare-plugin",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(prep.returncode, 0)
            self.assertEqual(parse_json_stdout(prep).get("failureReason"), "OUT_OF_ORDER_PLUGIN")

            # commit-plugin also out of order from TREE_FROZEN
            commit = run_py(
                TXN_PY,
                "commit-plugin",
                "--task",
                "WP-12A",
                "--commit-sha",
                self.FEAT_SHA,
                "--transactions",
                tmp,
            )
            self.assertNotEqual(commit.returncode, 0)
            self.assertEqual(parse_json_stdout(commit).get("failureReason"), "OUT_OF_ORDER_PLUGIN")

            # record-plugin-merged out of order
            merged = run_py(
                TXN_PY,
                "record-plugin-merged",
                "--task",
                "WP-12A",
                "--merge-sha",
                self.MERGED_SHA,
                "--transactions",
                tmp,
            )
            self.assertNotEqual(merged.returncode, 0)
            self.assertEqual(parse_json_stdout(merged).get("failureReason"), "OUT_OF_ORDER_PLUGIN")

    def test_commit_plugin_requires_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._init_at_state(tmp, "VERIFIED")
            commit = run_py(
                TXN_PY,
                "commit-plugin",
                "--task",
                "WP-12A",
                "--commit-sha",
                self.FEAT_SHA,
                "--transactions",
                tmp,
            )
            self.assertNotEqual(commit.returncode, 0)
            self.assertEqual(parse_json_stdout(commit).get("failureReason"), "OUT_OF_ORDER_PLUGIN")

    def test_plugin_committed_does_not_set_effective_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._init_at_state(tmp, "VERIFIED")
            merged = run_py(
                TXN_PY,
                "record-plugin-merged",
                "--task",
                "WP-12A",
                "--merge-sha",
                "4255a9f",  # short form
                "--transactions",
                tmp,
            )
            self.assertEqual(merged.returncode, 0, msg=merged.stdout + merged.stderr)
            payload = parse_json_stdout(merged)
            self.assertEqual(payload.get("state"), "PLUGIN_COMMITTED")
            self.assertIs(payload.get("EffectiveDone"), False)

            # declare-done still forbidden
            decl = run_py(
                TXN_PY,
                "record-plugin-merged",
                "--task",
                "WP-12A",
                "--merge-sha",
                self.MERGED_SHA,
                "--declare-done",
                "--transactions",
                tmp,
            )
            self.assertNotEqual(decl.returncode, 0)
            # already PLUGIN_COMMITTED → out of order OR declare-done first
            reason = parse_json_stdout(decl).get("failureReason")
            self.assertIn(reason, {"CALLER_DECLARED_DONE", "OUT_OF_ORDER_PLUGIN", "ALREADY_DONE_OR_FORGED"})

    def test_prepare_after_evidence_sealed_tolerated(self) -> None:
        """EVIDENCE_SEALED is a valid prereq for prepare-plugin (attach tolerate)."""
        with tempfile.TemporaryDirectory() as tmp:
            self._init_at_state(tmp, "EVIDENCE_SEALED")
            prep = run_py(
                TXN_PY,
                "prepare-plugin",
                "--task",
                "WP-12A",
                "--transactions",
                tmp,
            )
            self.assertEqual(prep.returncode, 0, msg=prep.stdout + prep.stderr)
            self.assertEqual(parse_json_stdout(prep).get("state"), "PLUGIN_PREPARED")
            self.assertFalse(parse_json_stdout(prep).get("EffectiveDone"))

            merged = run_py(
                TXN_PY,
                "record-plugin-merged",
                "--task",
                "WP-12A",
                "--merge-sha",
                self.MERGED_SHA,
                "--transactions",
                tmp,
            )
            self.assertEqual(merged.returncode, 0, msg=merged.stdout + merged.stderr)
            payload = parse_json_stdout(merged)
            self.assertEqual(payload.get("state"), "PLUGIN_COMMITTED")
            self.assertFalse(payload.get("EffectiveDone"))

    def test_real_verified_then_record_plugin_merged_integration(self) -> None:
        """One real phase-fence → record-plugin-merged path (no EffectiveDone)."""
        with tempfile.TemporaryDirectory() as tmp:
            txn_path = self._init_and_verify(tmp)
            merged = run_py(
                TXN_PY,
                "record-plugin-merged",
                "--task",
                "WP-12A",
                "--merge-sha",
                self.MERGED_SHA,
                "--transactions",
                tmp,
            )
            self.assertEqual(merged.returncode, 0, msg=merged.stdout + merged.stderr)
            payload = parse_json_stdout(merged)
            self.assertEqual(payload.get("state"), "PLUGIN_COMMITTED")
            self.assertFalse(payload.get("EffectiveDone"))
            receipt = json.loads(txn_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "PLUGIN_COMMITTED")
            self.assertFalse(receipt.get("EffectiveDone"))
            self.assertEqual(len(receipt.get("phaseEvents") or []), 4)


if __name__ == "__main__":
    unittest.main()
