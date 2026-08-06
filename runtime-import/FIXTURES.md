# WP-12A DRAFT fixtures (manifest / runtime inventory)

**Scope:** Plugin worktree scaffold (`runtime-import/` + `scripts/tests/test-runtime-import.sh`).
**Source:** adapted from verification `runs/wp-12a-draft/`.
**Plan:** four manifest negative fixtures + GREEN positive; fail-closed on unknown signature permissions, authority conflicts, missing DEX, resource ID conflicts.

Schema under test: [`manifest-map.schema.json`](./manifest-map.schema.json) (this directory) (`schemaVersion=wp12a-manifest-map/v1`).

Verifier policy (stderr signatures, non-zero exit on RED):

| Code | When |
| --- | --- |
| `UNKNOWN_SIGNATURE_PERMISSION` | declared or uses entry with `protectionLevel` in `{signature, signatureOrSystem}` whose `name` is not in `permissions.signatureKnown` |
| `AUTHORITY_CONFLICT` | two or more `authorities[].authority` values equal (case-sensitive) |
| `MISSING_DEX` | `dex.count == 0`, empty `dex.entries`, or no `classes.dex` entry |
| `RESOURCE_ID_CONFLICT` | two or more `resources.entries[]` share the same `id` |

---

## Negative fixtures (4)

Exact basenames for catalog `fixtureBasenames` / RED harness (no directory prefix):

### 1. `manifest-unknown-signature-permission.json`

| Field | Value |
| --- | --- |
| Kind | negative |
| Mutation | Declare/use a signature-level permission not present in `signatureKnown` |
| Expected exit | non-zero |
| Expected failure signature | `UNKNOWN_SIGNATURE_PERMISSION` |
| Match | stderr (and optional structured `failClosed.failures[].code`) |
| Inventory notes | Keep valid DEX, unique authorities, unique resource IDs so only this gate fires |

### 2. `manifest-authority-conflict.json`

| Field | Value |
| --- | --- |
| Kind | negative |
| Mutation | Two provider rows with the same `authority` string (different `componentName` allowed) |
| Expected exit | non-zero |
| Expected failure signature | `AUTHORITY_CONFLICT` |
| Match | stderr |
| Inventory notes | Signature permissions allowlisted; DEX present; resource IDs unique |

### 3. `manifest-missing-dex.json`

| Field | Value |
| --- | --- |
| Kind | negative |
| Mutation | `dex.count=0` and/or empty `entries` (no `classes.dex`) |
| Expected exit | non-zero |
| Expected failure signature | `MISSING_DEX` |
| Match | stderr |
| Inventory notes | Manifest/components may still look complete; gate is DEX inventory only |

### 4. `manifest-resource-id-conflict.json`

| Field | Value |
| --- | --- |
| Kind | negative |
| Mutation | Two `resources.entries` with the same `id` (e.g. `0x7f010001`) and different names |
| Expected exit | non-zero |
| Expected failure signature | `RESOURCE_ID_CONFLICT` |
| Match | stderr |
| Inventory notes | DEX present; authorities unique; signature permissions known |

---

## Positive fixture (1)

### 5. `manifest-inventory-pass.json`

| Field | Value |
| --- | --- |
| Kind | positive (GREEN) |
| Mutation | none — minimal valid official-APK-shaped inventory |
| Expected exit | `0` |
| Expected failure signature | *(none; `failClosed.ok=true`, `failures=[]`)* |
| Match | n/a |
| Inventory notes | At least one DEX (`classes.dex`); unique authorities; unique resource IDs; every signature-level permission name ∈ `signatureKnown`; all six inventory maps populated (`manifest`, `dex`, `resources`, `authorities`, `permissions`, `components`) |

---

## Catalog wiring (draft intent)

```text
fixtureBasenames:
  - manifest-unknown-signature-permission.json
  - manifest-authority-conflict.json
  - manifest-missing-dex.json
  - manifest-resource-id-conflict.json
  - manifest-inventory-pass.json

failureSignaturePolicy.RED:
  required: true
  match: stderr
  # RED suite must hit each of the four codes above at least once

expectedExit:
  RED: non-zero (real tool exit; not hard-coded)
  GREEN / REFACTOR / VERIFY: 0
```

## Fixture file locations (Plugin worktree)

Catalog basenames live under:

```text
scripts/tests/fixtures/
  manifest-unknown-signature-permission.json
  manifest-authority-conflict.json
  manifest-missing-dex.json
  manifest-resource-id-conflict.json
  manifest-inventory-pass.json   # optional positive (not required catalog exactFile)
```

Harness: `scripts/tests/test-runtime-import.sh` invokes
`scripts/verify-imported-runtime.sh --inventory <fixture> --mode <mode>` and asserts
non-zero exit + stderr tokens for the four negatives; exit 0 for the positive.

Schema: `runtime-import/manifest-map.schema.json` (`schemaVersion=wp12a-manifest-map/v1`).

## Out of scope

- Native/ABI/JNI closure (WP-12B / `native-libs.schema.json`).
- Device evidence collection (`--mode runtime-inventory`); fixtures are host-side import/verify only.
