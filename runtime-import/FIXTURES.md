# WP-12 runtime-import fixtures

**Scope:** Plugin worktree scaffold (`runtime-import/` + `scripts/tests/`).
**Plan:** fail-closed inventory gates for official APK import (WP-12A manifest map, WP-12B native/JNI closure).

| Task | Schema | Fixture basenames |
| --- | --- | --- |
| WP-12A | [`manifest-map.schema.json`](./manifest-map.schema.json) (`wp12a-manifest-map/v1`) | four manifest negatives + optional positive |
| WP-12B | [`native-libs.schema.json`](./native-libs.schema.json) (`wp12b-native-libs/v1`) | two native negatives |

---

# WP-12A DRAFT fixtures (manifest / runtime inventory)

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

## WP-12A Negative fixtures (4)

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

## WP-12A Positive fixture (1)

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

## WP-12A Catalog wiring (draft intent)

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

## WP-12A Fixture file locations (Plugin worktree)

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

---

# WP-12B fixtures (native / ABI / JNI closure)

**Source:** DEVELOPMENT WP-12B allowlist + fail-closed native closure goal (ABI, ELF machine/class, SONAME, DT_NEEDED, transitive deps).
**Plan:** two native negative fixtures (min); fail-closed on missing local deps and wrong-ABI placement (empty arm64 is also a RED code).

Schema under test: [`native-libs.schema.json`](./native-libs.schema.json) (`schemaVersion=wp12b-native-libs/v1`).

Verifier policy (stderr signatures, non-zero exit on RED):

| Code | When |
| --- | --- |
| `MISSING_NEEDED` | a lib's `needed[]` entry is not resolved by another lib in the same ABI and is not in `closure.systemNeeded` |
| `WRONG_ABI` | ELF `elfMachine`/`elfClass` does not match the containing `abis[].name` directory (e.g. `EM_ARM` under `arm64-v8a`) |
| `DUPLICATE_SONAME` | two or more libs in the same ABI claim the same non-null `soname` |
| `EMPTY_ARM64` | no `arm64-v8a` ABI row, or `arm64-v8a.libs` is empty |

Top-level inventory shape:

- `schemaVersion`, `packageName`, `apkSha256`
- `abis[]`: `{ name, libs[{ name, path, sha256, sizeBytes, soname, needed[], elfClass, elfMachine }] }`
- `jniLoadLibs[]`: Java-facing load names (`System.loadLibrary` surface)
- `closure`: `{ missingNeeded[], wrongAbi[], duplicateSoname[], systemNeeded[] }`
- `failClosed`: `{ ok, failures[{ code, message, detail? }] }`

---

## WP-12B Negative fixtures (2)

Exact basenames for catalog `fixtureBasenames` / RED harness (no directory prefix):

### 1. `native-missing-needed.json`

| Field | Value |
| --- | --- |
| Kind | negative |
| Mutation | `libwallpaperengine.so` DT_NEEDED includes local `libmissing_local_dep.so` which is absent from `abis[].libs` and from `systemNeeded` |
| Expected exit | non-zero |
| Expected failure signature | `MISSING_NEEDED` |
| Match | stderr (and structured `failClosed.failures[].code`) |
| Inventory notes | arm64-v8a present and ELF-correct; only the local missing dep gate fires |

### 2. `native-wrong-abi.json`

| Field | Value |
| --- | --- |
| Kind | negative |
| Mutation | `lib/arm64-v8a/libwallpaperengine.so` has `elfMachine=EM_ARM` / `elfClass=ELFCLASS32` (32-bit ARM binary under arm64 dir) |
| Expected exit | non-zero |
| Expected failure signature | `WRONG_ABI` |
| Match | stderr |
| Inventory notes | DT_NEEDED only public system libs; no duplicate SONAME; demonstrates ABI/ELF mismatch (EMPTY_ARM64 is a separate code for empty/missing arm64-v8a) |

---

## WP-12B Catalog wiring (draft intent)

```text
fixtureBasenames:
  - native-missing-needed.json
  - native-wrong-abi.json

failureSignaturePolicy.RED:
  required: true
  match: stderr
  # RED suite must hit MISSING_NEEDED and WRONG_ABI at least once

expectedExit:
  RED: non-zero (real tool exit; not hard-coded)
  GREEN / REFACTOR / VERIFY: 0
```

## WP-12B Fixture file locations (Plugin worktree)

```text
scripts/tests/fixtures/
  native-missing-needed.json
  native-wrong-abi.json
```

Schema: `runtime-import/native-libs.schema.json` (`schemaVersion=wp12b-native-libs/v1`).

Harness note: WP-12B RED/GREEN extend the WP-12A import/verify scripts (DEVELOPMENT allowlist: modify the three WP-12A scripts) to accept native inventories; fixtures remain host-side import/verify only until device `native-closure` evidence collection.

---

## Out of scope (this FIXTURES.md)

- Device evidence collection (`--mode native-closure` / runtime-inventory); fixtures are host-side schema-shaped inventories.
- WP-12C+ embedded adapter / device E2E fixtures.
