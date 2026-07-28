# pkg2mpkg Rust/MPKG Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable Rust foundation that inspects Wallpaper Engine projects, rejects Web/Application, resolves Scene export plans, and safely reads, writes, and verifies PKGM0018/PKGM0020 containers.

**Architecture:** Create an isolated Rust workspace under pkg2mpkg with focused core, CLI, and synthetic-fixture crates. The core owns typed errors, source analysis, preset and resolution math, MPKG I/O, and serializable ExportPlan values; the CLI is a thin adapter over those APIs. This plan deliberately stops before proprietary texture conversion, FFmpeg, Scene capture, ADB, and egui, which are covered by the next 3 independently testable plans.

**Tech Stack:** Rust 1.97.0, edition 2024, serde/serde_json, thiserror, indexmap, clap, tempfile, assert_cmd, predicates.

## Global Constraints

- Windows behavior evidence comes only from /Users/anpple/Codex/WallpaperEngine/research/Wallpaper Engine.2.8.26.
- Do not import code or behavioral assumptions from the repository's existing pkg2mpkg tools or analysis documents.
- Target the unmodified official io.wallpaperengine.weclient Android 2.8.8 application.
- Support only Scene and Video; reject Web and Application through every public entry point with exit code 3.
- Default future output version is PKGM0020; the reader and verifier accept PKGM0018 and PKGM0020.
- Preserve unknown project.json fields and never modify source files.
- Reject absolute, parent-traversing, NUL-containing, backslash, duplicate, out-of-bounds, overlapping, or oversized MPKG entries.
- Reject output sizes greater than or equal to 4 GiB.
- Write output through a same-directory partial file, sync it, self-verify it, and atomically rename it.
- Do not commit official Wallpaper Engine binaries, DLLs, APKs, MPKGs, or extracted copyrighted assets.
- Implement in an isolated git worktree based on the approved design commits; do not touch the dirty Android worktree.
- For this plan, deny unsafe Rust in every crate.

## Plan Series

1. This plan: Rust workspace, source inspection, presets, resolution math, MPKG reader/writer, ExportPlan, CLI, and synthetic fixtures.
2. Dynamic Scene plan: desktop PKG/resource graph, mobile project builder, texture backend, dynamic MPKG export, and Dino Run Android validation.
3. Video/pre-render plan: FFmpeg, geometry filters, Video MPKG, SceneCaptureBackend, Windows duration oracle, and High Performance export.
4. Device/GUI/release plan: ADB Auto, device verification, egui workflow, platform bundles, and release qualification.

## File Map

~~~
pkg2mpkg/
  Cargo.toml                         Workspace members and shared dependencies
  Cargo.lock                        Exact dependency lock
  rust-toolchain.toml               Rust 1.97.0, rustfmt, clippy
  README.md                         Foundation capabilities and commands
  crates/
    core/
      Cargo.toml
      src/
        lib.rs                      Public exports and unsafe-code denial
        error.rs                    Stable stages, error codes, and Result
        property.rs                 Mobile property sanitizer
        project/
          mod.rs                    Project API exports
          kind.rs                   WallpaperKind parsing and inference
          manifest.rs               Lossless project.json representation
          source.rs                 Input path resolution and inspection
        profile.rs                  Windows 2.8.26 Scene preset matrix
        resolution.rs               Dimensions, crop mode, alignment, geometry
        export.rs                   ExportRequest and immutable ExportPlan
        backend.rs                  Capability contracts for Plans 2 and 3
        mpkg/
          mod.rs                    MPKG public exports and version enum
          path.rs                   Archive path validation
          reader.rs                 PKGM0018/0020 parser and entry reads
          writer.rs                 Deterministic and atomic writer
      tests/
        error_contract.rs
        project_inspection.rs
        property_sanitizer.rs
        profile_matrix.rs
        resolution_geometry.rs
        export_plan.rs
        mpkg_reader.rs
        mpkg_malformed.rs
        mpkg_roundtrip.rs
        mpkg_atomic.rs
    fixtures/
      Cargo.toml
      src/
        lib.rs                      Synthetic fixture exports
        mpkg.rs                     Copyright-free MPKG byte builders
        project.rs                  Copyright-free project directory builders
      tests/
        reference_dino.rs           Ignored local reference check
    cli/
      Cargo.toml
      src/
        main.rs                     Process entry and exit-code mapping
        args.rs                     clap command model
        output.rs                   Text/JSON rendering
        commands/
          mod.rs
          inspect.rs
          verify.rs
          export.rs                 Dry-run only in this foundation
      tests/
        cli_inspect.rs
        cli_verify.rs
        cli_export_dry_run.rs
        cli_error_codes.rs
~~~

---

### Task 1: Workspace, Typed Errors, and Crate Boundaries

**Files:**
- Create: pkg2mpkg/Cargo.toml
- Create: pkg2mpkg/Cargo.lock
- Create: pkg2mpkg/rust-toolchain.toml
- Create: pkg2mpkg/crates/core/Cargo.toml
- Create: pkg2mpkg/crates/core/src/lib.rs
- Create: pkg2mpkg/crates/core/src/error.rs
- Create: pkg2mpkg/crates/core/tests/error_contract.rs
- Create: pkg2mpkg/crates/fixtures/Cargo.toml
- Create: pkg2mpkg/crates/fixtures/src/lib.rs
- Create: pkg2mpkg/crates/cli/Cargo.toml
- Create: pkg2mpkg/crates/cli/src/main.rs

**Interfaces:**
- Produces: pkg2mpkg_core::Result<T>
- Produces: pkg2mpkg_core::Error with code() -> ErrorCode and stage() -> Stage
- Produces: ErrorCode::exit_code() -> u8
- Consumes: no earlier tasks

- [ ] **Step 1: Create the workspace manifests**

Write pkg2mpkg/Cargo.toml:

~~~toml
[workspace]
members = ["crates/core", "crates/fixtures", "crates/cli"]
resolver = "3"

[workspace.package]
version = "0.1.0"
edition = "2024"
rust-version = "1.85"
license = "MIT"

[workspace.dependencies]
assert_cmd = "2.0"
clap = { version = "4.5", features = ["derive"] }
indexmap = { version = "2.11", features = ["serde"] }
predicates = "3.1"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
tempfile = "3.20"
thiserror = "2.0"
~~~

Write pkg2mpkg/rust-toolchain.toml:

~~~toml
[toolchain]
channel = "1.97.0"
components = ["clippy", "rustfmt"]
profile = "minimal"
~~~

Write crates/core/Cargo.toml:

~~~toml
[package]
name = "pkg2mpkg-core"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true

[dependencies]
indexmap.workspace = true
serde.workspace = true
serde_json.workspace = true
tempfile.workspace = true
thiserror.workspace = true

[dev-dependencies]
pkg2mpkg-fixtures = { path = "../fixtures" }
~~~

Write crates/fixtures/Cargo.toml without a normal dependency on core, avoiding a core ↔ fixture cycle:

~~~toml
[package]
name = "pkg2mpkg-fixtures"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true

[dependencies]
serde_json.workspace = true
tempfile.workspace = true

[dev-dependencies]
pkg2mpkg-core = { path = "../core" }
~~~

Write crates/cli/Cargo.toml:

~~~toml
[package]
name = "pkg2mpkg"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true

[dependencies]
clap.workspace = true
pkg2mpkg-core = { path = "../core" }
serde.workspace = true
serde_json.workspace = true

[dev-dependencies]
assert_cmd.workspace = true
pkg2mpkg-fixtures = { path = "../fixtures" }
predicates.workspace = true
tempfile.workspace = true
~~~

Initialize core/src/lib.rs with #![forbid(unsafe_code)], mod error, and the public error re-exports. Initialize fixtures/src/lib.rs with #![forbid(unsafe_code)]. Initialize cli/src/main.rs with #![forbid(unsafe_code)] and an empty main function so Cargo can generate Cargo.lock before the failing test is added.

- [ ] **Step 2: Write the failing public error-contract test**

Write pkg2mpkg/crates/core/tests/error_contract.rs:

~~~rust
use pkg2mpkg_core::{Error, ErrorCode, Stage};

#[test]
fn unsupported_type_has_stable_contract() {
    let error = Error::unsupported_type("web");
    assert_eq!(error.code(), ErrorCode::UnsupportedWallpaperType);
    assert_eq!(error.stage(), Stage::Inspect);
    assert_eq!(error.code().exit_code(), 3);
    assert!(error.to_string().contains("web"));
}

#[test]
fn invalid_package_maps_to_exit_code_four() {
    let error = Error::invalid_mpkg("entry range exceeds file");
    assert_eq!(error.code(), ErrorCode::InvalidMpkg);
    assert_eq!(error.stage(), Stage::Verify);
    assert_eq!(error.code().exit_code(), 4);
}
~~~

- [ ] **Step 3: Run the test and verify it fails**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test error_contract
~~~

Expected: compilation fails because Error, ErrorCode, and Stage do not exist.

- [ ] **Step 4: Implement stable errors**

Write pkg2mpkg/crates/core/src/error.rs with these exact public enums:

~~~rust
use std::{io, path::PathBuf};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Stage {
    Arguments,
    Inspect,
    Plan,
    Unpack,
    Convert,
    Pack,
    Verify,
    Device,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    InvalidArguments,
    UnsupportedWallpaperType,
    InvalidProject,
    InvalidMpkg,
    BackendUnavailable,
    ConversionFailed,
    OutputIo,
    PackageTooLarge,
    VerificationFailed,
    DeviceFailed,
    Cancelled,
}

impl ErrorCode {
    pub const fn exit_code(self) -> u8 {
        match self {
            Self::InvalidArguments => 2,
            Self::UnsupportedWallpaperType => 3,
            Self::InvalidProject | Self::InvalidMpkg => 4,
            Self::BackendUnavailable => 5,
            Self::ConversionFailed => 6,
            Self::OutputIo | Self::PackageTooLarge => 7,
            Self::VerificationFailed => 8,
            Self::DeviceFailed => 9,
            Self::Cancelled => 130,
        }
    }
}

#[derive(Debug, Error)]
pub enum Error {
    #[error("invalid arguments: {reason}")]
    InvalidArguments { reason: String },
    #[error("unsupported wallpaper type: {kind}")]
    UnsupportedWallpaperType { kind: String },
    #[error("invalid project: {reason}")]
    InvalidProject { reason: String },
    #[error("invalid MPKG: {reason}")]
    InvalidMpkg { reason: String },
    #[error("I/O failure during {stage:?} at {path}: {source}")]
    Io {
        stage: Stage,
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("backend unavailable: {backend}")]
    BackendUnavailable { backend: String },
    #[error("conversion failed: {reason}")]
    ConversionFailed { reason: String },
    #[error("package size {size} exceeds the 4 GiB limit")]
    PackageTooLarge { size: u64 },
    #[error("verification failed: {reason}")]
    VerificationFailed { reason: String },
    #[error("device operation failed: {reason}")]
    DeviceFailed { reason: String },
    #[error("operation cancelled")]
    Cancelled,
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub fn unsupported_type(kind: impl Into<String>) -> Self {
        Self::UnsupportedWallpaperType { kind: kind.into() }
    }

    pub fn invalid_mpkg(reason: impl Into<String>) -> Self {
        Self::InvalidMpkg { reason: reason.into() }
    }

    pub const fn code(&self) -> ErrorCode {
        match self {
            Self::InvalidArguments { .. } => ErrorCode::InvalidArguments,
            Self::UnsupportedWallpaperType { .. } => ErrorCode::UnsupportedWallpaperType,
            Self::InvalidProject { .. } => ErrorCode::InvalidProject,
            Self::InvalidMpkg { .. } => ErrorCode::InvalidMpkg,
            Self::Io { stage, .. } => match stage {
                Stage::Arguments | Stage::Plan => ErrorCode::InvalidArguments,
                Stage::Inspect | Stage::Unpack => ErrorCode::InvalidProject,
                Stage::Convert => ErrorCode::ConversionFailed,
                Stage::Pack => ErrorCode::OutputIo,
                Stage::Verify => ErrorCode::InvalidMpkg,
                Stage::Device => ErrorCode::DeviceFailed,
            },
            Self::BackendUnavailable { .. } => ErrorCode::BackendUnavailable,
            Self::ConversionFailed { .. } => ErrorCode::ConversionFailed,
            Self::PackageTooLarge { .. } => ErrorCode::PackageTooLarge,
            Self::VerificationFailed { .. } => ErrorCode::VerificationFailed,
            Self::DeviceFailed { .. } => ErrorCode::DeviceFailed,
            Self::Cancelled => ErrorCode::Cancelled,
        }
    }

    pub const fn stage(&self) -> Stage {
        match self {
            Self::InvalidArguments { .. } => Stage::Arguments,
            Self::UnsupportedWallpaperType { .. } | Self::InvalidProject { .. } => Stage::Inspect,
            Self::BackendUnavailable { .. } | Self::Cancelled => Stage::Plan,
            Self::ConversionFailed { .. } => Stage::Convert,
            Self::Io { stage, .. } => *stage,
            Self::PackageTooLarge { .. } => Stage::Pack,
            Self::InvalidMpkg { .. } | Self::VerificationFailed { .. } => Stage::Verify,
            Self::DeviceFailed { .. } => Stage::Device,
        }
    }
}
~~~

Re-export Error, ErrorCode, Result, and Stage from lib.rs.

- [ ] **Step 5: Run format, lint, and tests**

Run:

~~~bash
cd pkg2mpkg
cargo fmt --all -- --check
cargo clippy -p pkg2mpkg-core --all-targets -- -D warnings
cargo test -p pkg2mpkg-core --test error_contract
~~~

Expected: all commands pass.

- [ ] **Step 6: Commit Task 1**

Run:

~~~bash
git add pkg2mpkg/Cargo.toml pkg2mpkg/Cargo.lock pkg2mpkg/rust-toolchain.toml \
  pkg2mpkg/crates/core pkg2mpkg/crates/fixtures pkg2mpkg/crates/cli
git commit -m "feat(pkg2mpkg): establish Rust workspace and errors"
~~~

---

### Task 2: Lossless Project Inspection and Type Gate

**Files:**
- Create: pkg2mpkg/crates/core/src/project/mod.rs
- Create: pkg2mpkg/crates/core/src/project/kind.rs
- Create: pkg2mpkg/crates/core/src/project/manifest.rs
- Create: pkg2mpkg/crates/core/src/project/source.rs
- Create: pkg2mpkg/crates/core/src/property.rs
- Modify: pkg2mpkg/crates/core/src/lib.rs
- Modify: pkg2mpkg/crates/core/src/error.rs
- Test: pkg2mpkg/crates/core/tests/project_inspection.rs
- Test: pkg2mpkg/crates/core/tests/property_sanitizer.rs

**Interfaces:**
- Produces: WallpaperKind::{Scene, Video, Web, Application}
- Produces: ProjectManifest::parse(bytes: &[u8]) -> Result<ProjectManifest>
- Produces: inspect_source(path: &Path) -> Result<SourceProject>
- Produces: sanitize_mobile_properties(input: &serde_json::Map<String, Value>) -> Map<String, Value>
- Consumes: Error, ErrorCode, Result, and Stage from Task 1

- [ ] **Step 1: Write failing type and lossless-manifest tests**

Write project_inspection.rs:

~~~rust
use std::fs;
use pkg2mpkg_core::{inspect_source, ErrorCode, WallpaperKind};
use tempfile::tempdir;

#[test]
fn scene_project_preserves_unknown_fields() {
    let dir = tempdir().unwrap();
    fs::write(dir.path().join("scene.json"), b"{}").unwrap();
    fs::write(
        dir.path().join("project.json"),
        br#"{"title":"Dino","type":"scene","file":"scene.json","vendor":{"x":7}}"#,
    ).unwrap();

    let source = inspect_source(dir.path()).unwrap();
    assert_eq!(source.kind, WallpaperKind::Scene);
    assert_eq!(source.title, "Dino");
    assert_eq!(source.manifest.raw()["vendor"]["x"], 7);
}

#[test]
fn html_and_exe_cannot_bypass_the_type_gate_when_type_is_missing() {
    for (entry, expected) in [
        ("index.html", WallpaperKind::Web),
        ("demo.exe", WallpaperKind::Application),
    ] {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(entry), b"x").unwrap();
        fs::write(
            dir.path().join("project.json"),
            format!(r#"{{"title":"blocked","file":"{entry}"}}"#),
        ).unwrap();
        let error = inspect_source(dir.path()).unwrap_err();
        assert_eq!(error.code(), ErrorCode::UnsupportedWallpaperType);
        assert!(error.to_string().contains(expected.as_str()));
    }
}
~~~

- [ ] **Step 2: Write the failing property-sanitizer test**

Write property_sanitizer.rs:

~~~rust
use pkg2mpkg_core::sanitize_mobile_properties;
use serde_json::{Map, json};

#[test]
fn strips_only_the_windows_mobile_property_blacklist() {
    let input: Map<String, serde_json::Value> = serde_json::from_value(json!({
        "alignment": {"value": "center"},
        "alignmentx": {"value": 0.5},
        "pluginledextensionsenableleds": {"value": true},
        "wec_hue": {"value": 0.8},
        "rate": {"value": 2.0},
        "dino": {"value": "vita"},
        "Alignment": {"value": "user-defined-different-key"}
    })).unwrap();

    let output = sanitize_mobile_properties(&input);
    assert_eq!(output.len(), 2);
    assert_eq!(output["dino"]["value"], "vita");
    assert_eq!(output["Alignment"]["value"], "user-defined-different-key");
}
~~~

- [ ] **Step 3: Run both tests and verify failure**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test project_inspection --test property_sanitizer
~~~

Expected: compilation fails because the project and property APIs do not exist.

- [ ] **Step 4: Implement WallpaperKind and lossless ProjectManifest**

Implement kind.rs:

~~~rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum WallpaperKind {
    Scene,
    Video,
    Web,
    Application,
}

impl WallpaperKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Scene => "scene",
            Self::Video => "video",
            Self::Web => "web",
            Self::Application => "application",
        }
    }
}
~~~

ProjectManifest stores the original serde_json::Value and exposes title(), kind(), entry(), raw(), and into_raw(). Parse explicit type case-insensitively. When type is absent, infer .html/.htm as Web, .exe as Application, .mp4/.webm as Video, and JSON as Scene only when the entry JSON parses to an object containing a Scene root marker such as camera, objects, or general.

- [ ] **Step 5: Implement SourceProject and inspect_source**

Use this exact public shape:

~~~rust
#[derive(Debug, Clone)]
pub struct SourceProject {
    pub root: PathBuf,
    pub project_file: Option<PathBuf>,
    pub entry_file: PathBuf,
    pub title: String,
    pub kind: WallpaperKind,
    pub manifest: ProjectManifest,
}

pub fn inspect_source(path: &Path) -> Result<SourceProject>;
~~~

Directory inputs resolve root/project.json. project.json inputs resolve their parent. A .pkg input searches its directory and then one parent for project.json. Direct MP4/WebM creates a minimal in-memory manifest with title from file_stem and type video. Any resolved Web/Application returns Error::UnsupportedWallpaperType before SourceProject is returned.

- [ ] **Step 6: Implement the exact property blacklist**

property.rs must define a constant slice containing:

~~~rust
const MOBILE_PROPERTY_BLACKLIST: &[&str] = &[
    "alignment",
    "alignmentx",
    "alignmenty",
    "alignmentz",
    "alignmentposition",
    "alignmentfliph",
    "pluginledextensionsenableleds",
    "wec_e",
    "wec_brs",
    "wec_con",
    "wec_sat",
    "wec_hue",
    "rate",
];
~~~

Return a cloned map with exact-case matches removed; never mutate the caller's map or recursively remove similarly named Scene fields.

- [ ] **Step 7: Run the focused and full core tests**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test project_inspection --test property_sanitizer
cargo test -p pkg2mpkg-core
~~~

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

Run:

~~~bash
git add pkg2mpkg/crates/core/src/project pkg2mpkg/crates/core/src/property.rs \
  pkg2mpkg/crates/core/src/lib.rs pkg2mpkg/crates/core/src/error.rs \
  pkg2mpkg/crates/core/tests/project_inspection.rs \
  pkg2mpkg/crates/core/tests/property_sanitizer.rs
git commit -m "feat(pkg2mpkg): inspect projects and reject unsupported types"
~~~

---

### Task 3: Windows Presets and Resolution Geometry

**Files:**
- Create: pkg2mpkg/crates/core/src/profile.rs
- Create: pkg2mpkg/crates/core/src/resolution.rs
- Modify: pkg2mpkg/crates/core/src/lib.rs
- Modify: pkg2mpkg/crates/core/src/error.rs
- Test: pkg2mpkg/crates/core/tests/profile_matrix.rs
- Test: pkg2mpkg/crates/core/tests/resolution_geometry.rs

**Interfaces:**
- Produces: resolve_scene_profile(profile: SceneProfile, class: ContentClass) -> SceneMode
- Produces: Dimensions::new(width: u32, height: u32) -> Result<Dimensions>
- Produces: Dimensions::new_h264(width: u32, height: u32) -> Result<Dimensions>
- Produces: resolve_video_geometry(source, boundary, crop, alignment) -> Result<ResolvedVideoGeometry>
- Consumes: Error and Result from Task 1

- [ ] **Step 1: Write the failing Windows preset matrix test**

Write profile_matrix.rs:

~~~rust
use pkg2mpkg_core::{
    Compression, ContentClass, Reduction, SceneMode, SceneProfile, resolve_scene_profile,
};

#[test]
fn matches_windows_2826_dynamic_matrix() {
    let cases = [
        (SceneProfile::High, ContentClass::PixelArt, Compression::HighQuality, Reduction::Original),
        (SceneProfile::High, ContentClass::Normal, Compression::HighPerformance, Reduction::Original),
        (SceneProfile::High, ContentClass::Uhd, Compression::HighPerformance, Reduction::X2),
        (SceneProfile::Balanced, ContentClass::PixelArt, Compression::HighPerformance, Reduction::Original),
        (SceneProfile::Balanced, ContentClass::Normal, Compression::HighPerformance, Reduction::X2),
        (SceneProfile::Balanced, ContentClass::Uhd, Compression::HighPerformance, Reduction::X4),
    ];

    for (profile, class, compression, reduction) in cases {
        assert_eq!(
            resolve_scene_profile(profile, class),
            SceneMode::Dynamic { compression, reduction }
        );
    }
    assert_eq!(
        resolve_scene_profile(SceneProfile::Performance, ContentClass::Normal),
        SceneMode::PreRendered
    );
}
~~~

- [ ] **Step 2: Write failing geometry tests**

Write resolution_geometry.rs:

~~~rust
use pkg2mpkg_core::{
    Alignment, CropMode, Dimensions, ErrorCode, resolve_video_geometry,
};

#[test]
fn cover_uses_the_exact_landscape_car_canvas() {
    let geometry = resolve_video_geometry(
        Dimensions::new(1080, 1920).unwrap(),
        Dimensions::new(1920, 1080).unwrap(),
        CropMode::Cover,
        Alignment::CENTER,
    ).unwrap();
    assert_eq!(geometry.output, Dimensions::new(1920, 1080).unwrap());
    assert!(geometry.crop.is_some());
}

#[test]
fn keep_aspect_uses_exact_as_a_boundary_without_padding() {
    let geometry = resolve_video_geometry(
        Dimensions::new(1920, 1080).unwrap(),
        Dimensions::new(1000, 1000).unwrap(),
        CropMode::KeepAspect,
        Alignment::CENTER,
    ).unwrap();
    assert_eq!(geometry.output, Dimensions::new(1000, 562).unwrap());
    assert!(geometry.crop.is_none());
}

#[test]
fn odd_h264_target_is_rejected_instead_of_rounded() {
    let source = Dimensions::new(1919, 1080).unwrap();
    assert_eq!(source.width, 1919);

    let error = Dimensions::new_h264(1919, 1080).unwrap_err();
    assert_eq!(error.code(), ErrorCode::InvalidArguments);
    assert!(error.to_string().contains("1920"));
}
~~~

- [ ] **Step 3: Run tests and verify failure**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test profile_matrix --test resolution_geometry
~~~

Expected: compilation fails because profile and geometry APIs do not exist.

- [ ] **Step 4: Implement profile enums and exact matrix**

Define serde-enabled enums Compression, Reduction, ContentClass, SceneProfile, and SceneMode. Use Original as the Rust name serialized to high_quality, X2 serialized to reduction_x2, and X4 serialized to reduction_x4. SceneProfile::Custom carries explicit compression and reduction values.

resolve_scene_profile must be a total match with no default branch.

- [ ] **Step 5: Implement integer geometry**

Define:

~~~rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Dimensions {
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CropMode {
    Cover,
    KeepAspect,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Alignment {
    pub x: u8,
    pub y: u8,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CropRect {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResolvedVideoGeometry {
    pub output: Dimensions,
    pub crop: Option<CropRect>,
}
~~~

`Dimensions::new` validates only that both dimensions are non-zero, because source media can legally have odd dimensions. `Dimensions::new_h264` additionally requires both dimensions to be even and reports the nearest lower/upper valid values. Validate 1..=100 for alignment. Use checked u64 products for aspect comparisons. `resolve_video_geometry` validates its boundary through the H.264 rule; KeepAspect scales within that boundary, rounds each result down to a positive even number, and never adds padding. Cover returns the exact boundary and computes a source CropRect positioned by alignment.

- [ ] **Step 6: Run focused tests and clippy**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test profile_matrix --test resolution_geometry
cargo clippy -p pkg2mpkg-core --all-targets -- -D warnings
~~~

Expected: all commands pass.

- [ ] **Step 7: Commit Task 3**

Run:

~~~bash
git add pkg2mpkg/crates/core/src/profile.rs pkg2mpkg/crates/core/src/resolution.rs \
  pkg2mpkg/crates/core/src/lib.rs pkg2mpkg/crates/core/src/error.rs \
  pkg2mpkg/crates/core/tests/profile_matrix.rs \
  pkg2mpkg/crates/core/tests/resolution_geometry.rs
git commit -m "feat(pkg2mpkg): resolve mobile profiles and geometry"
~~~

---

### Task 4: Safe PKGM0018/PKGM0020 Reader

**Files:**
- Create: pkg2mpkg/crates/core/src/mpkg/mod.rs
- Create: pkg2mpkg/crates/core/src/mpkg/path.rs
- Create: pkg2mpkg/crates/core/src/mpkg/reader.rs
- Modify: pkg2mpkg/crates/core/src/lib.rs
- Modify: pkg2mpkg/crates/core/src/error.rs
- Create: pkg2mpkg/crates/fixtures/src/mpkg.rs
- Modify: pkg2mpkg/crates/fixtures/src/lib.rs
- Test: pkg2mpkg/crates/core/tests/mpkg_reader.rs
- Test: pkg2mpkg/crates/core/tests/mpkg_malformed.rs

**Interfaces:**
- Produces: ContainerVersion::{Pkgm0018, Pkgm0020} with as_magic() -> &'static str
- Produces: MpkgArchive::open(path: &Path) -> Result<MpkgArchive>
- Produces: MpkgArchive::entries() -> &[MpkgEntry]
- Produces: MpkgArchive::read_entry(path: &str) -> Result<Vec<u8>>
- Consumes: typed errors from Task 1

- [ ] **Step 1: Add a copyright-free synthetic MPKG builder**

In fixtures/mpkg.rs, build raw packages using the observed directory layout:

~~~rust
pub fn raw_mpkg(version: &str, entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut table = Vec::new();
    let mut payload = Vec::new();
    for (path, bytes) in entries {
        table.extend_from_slice(&(path.len() as u32).to_le_bytes());
        table.extend_from_slice(path.as_bytes());
        table.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        table.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
        payload.extend_from_slice(bytes);
    }
    let mut out = Vec::new();
    out.extend_from_slice(&8u32.to_le_bytes());
    out.extend_from_slice(version.as_bytes());
    out.extend_from_slice(&(entries.len() as u32).to_le_bytes());
    out.extend_from_slice(&table);
    out.extend_from_slice(&payload);
    out
}
~~~

Use it only with PKGM0018 and PKGM0020.

- [ ] **Step 2: Write failing valid-reader tests**

Write mpkg_reader.rs:

~~~rust
use std::fs;
use pkg2mpkg_core::{ContainerVersion, MpkgArchive};
use pkg2mpkg_fixtures::raw_mpkg;
use tempfile::tempdir;

#[test]
fn reads_v18_and_v20_directories_and_payloads() {
    for (magic, version) in [
        ("PKGM0018", ContainerVersion::Pkgm0018),
        ("PKGM0020", ContainerVersion::Pkgm0020),
    ] {
        let dir = tempdir().unwrap();
        let path = dir.path().join("sample.mpkg");
        fs::write(&path, raw_mpkg(magic, &[
            ("project.json", br#"{"type":"scene"}"#),
            ("scene.json", br#"{"objects":[]}"#),
        ])).unwrap();
        let archive = MpkgArchive::open(&path).unwrap();
        assert_eq!(archive.version(), version);
        assert_eq!(archive.entries().len(), 2);
        assert_eq!(archive.read_entry("project.json").unwrap(), br#"{"type":"scene"}"#);
    }
}
~~~

- [ ] **Step 3: Write failing malformed-container tests**

Build malformed directories without going through the safe fixture helper:

~~~rust
struct RawEntry<'a> {
    path: &'a [u8],
    offset: u32,
    size: u32,
}

fn custom_raw(magic: &[u8], count: u32, entries: &[RawEntry<'_>], payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(&(magic.len() as u32).to_le_bytes());
    out.extend_from_slice(magic);
    out.extend_from_slice(&count.to_le_bytes());
    for entry in entries {
        out.extend_from_slice(&(entry.path.len() as u32).to_le_bytes());
        out.extend_from_slice(entry.path);
        out.extend_from_slice(&entry.offset.to_le_bytes());
        out.extend_from_slice(&entry.size.to_le_bytes());
    }
    out.extend_from_slice(payload);
    out
}

fn malformed_cases() -> Vec<(&'static str, Vec<u8>)> {
    let one = |path: &'static [u8], offset, size, payload: &'static [u8]| {
        custom_raw(
            b"PKGM0020",
            1,
            &[RawEntry { path, offset, size }],
            payload,
        )
    };
    vec![
        ("parent", one(b"../x", 0, 1, b"x")),
        ("absolute", one(b"/x", 0, 1, b"x")),
        ("drive", one(b"C:/x", 0, 1, b"x")),
        ("backslash", one(br"a\b", 0, 1, b"x")),
        ("nul", one(b"a\0b", 0, 1, b"x")),
        ("invalid_utf8", one(&[0xff], 0, 1, b"x")),
        (
            "duplicate",
            custom_raw(
                b"PKGM0020",
                2,
                &[
                    RawEntry { path: b"a", offset: 0, size: 1 },
                    RawEntry { path: b"a", offset: 1, size: 1 },
                ],
                b"xy",
            ),
        ),
        ("offset", one(b"a", 2, 1, b"x")),
        ("size", one(b"a", 0, 2, b"x")),
        (
            "overlap",
            custom_raw(
                b"PKGM0020",
                2,
                &[
                    RawEntry { path: b"a", offset: 0, size: 2 },
                    RawEntry { path: b"b", offset: 1, size: 2 },
                ],
                b"xyz",
            ),
        ),
        ("magic_length", custom_raw(b"PKGM020", 0, &[], b"")),
        ("unknown_magic", custom_raw(b"PKGM9999", 0, &[], b"")),
        (
            "entry_count",
            custom_raw(b"PKGM0020", 1_000_001, &[], b""),
        ),
    ]
}

#[test]
fn rejects_malformed_archives() {
    let dir = tempdir().unwrap();
    let mut cases = malformed_cases();
    let mut excessive_path = Vec::new();
    excessive_path.extend_from_slice(&8u32.to_le_bytes());
    excessive_path.extend_from_slice(b"PKGM0020");
    excessive_path.extend_from_slice(&1u32.to_le_bytes());
    excessive_path.extend_from_slice(&16_385u32.to_le_bytes());
    cases.push(("path_length", excessive_path));

for (name, bytes) in cases {
    let path = dir.path().join(format!("{name}.mpkg"));
    fs::write(&path, bytes).unwrap();
    let error = MpkgArchive::open(&path).unwrap_err();
    assert_eq!(error.code(), ErrorCode::InvalidMpkg, "{name}");
}
}
~~~

- [ ] **Step 4: Run tests and verify failure**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test mpkg_reader --test mpkg_malformed
~~~

Expected: compilation fails because the MPKG reader does not exist.

- [ ] **Step 5: Implement archive path validation**

Implement:

~~~rust
pub(crate) fn validate_archive_path(path: &str) -> Result<String> {
    let bytes = path.as_bytes();
    let drive_prefix = bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':';
    if path.is_empty()
        || path.contains('\0')
        || path.contains('\\')
        || path.starts_with('/')
        || drive_prefix
        || path.split('/').any(|part| part.is_empty() || part == "." || part == "..")
    {
        return Err(Error::invalid_mpkg(format!("unsafe archive path: {path:?}")));
    }
    Ok(path.to_owned())
}
~~~

- [ ] **Step 6: Implement the bounded reader**

Parse all integers as little-endian u32 and convert to u64 before arithmetic. Store entry offsets relative to payload_start, validate checked_add(offset, size) <= payload_len, sort a temporary list by offset to reject overlap, then retain original directory order publicly.

Use:

~~~rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ContainerVersion {
    Pkgm0018,
    Pkgm0020,
}

impl ContainerVersion {
    pub const fn as_magic(self) -> &'static str {
        match self {
            Self::Pkgm0018 => "PKGM0018",
            Self::Pkgm0020 => "PKGM0020",
        }
    }

    fn from_magic(magic: &[u8]) -> Result<Self> {
        match magic {
            b"PKGM0018" => Ok(Self::Pkgm0018),
            b"PKGM0020" => Ok(Self::Pkgm0020),
            _ => Err(Error::invalid_mpkg("unsupported container magic")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MpkgEntry {
    pub path: String,
    pub offset: u64,
    pub size: u64,
}

pub struct MpkgArchive {
    source: PathBuf,
    version: ContainerVersion,
    payload_start: u64,
    entries: Vec<MpkgEntry>,
    by_path: IndexMap<String, usize>,
}
~~~

read_entry opens the source file afresh, seeks to payload_start + offset, takes exactly size bytes, and rejects an unexpected EOF.

- [ ] **Step 7: Run all core and fixture tests**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-fixtures
cargo test -p pkg2mpkg-core --test mpkg_reader --test mpkg_malformed
cargo test -p pkg2mpkg-core
~~~

Expected: all tests pass.

- [ ] **Step 8: Commit Task 4**

Run:

~~~bash
git add pkg2mpkg/crates/core/src/mpkg pkg2mpkg/crates/core/src/lib.rs \
  pkg2mpkg/crates/core/src/error.rs pkg2mpkg/crates/core/tests/mpkg_reader.rs \
  pkg2mpkg/crates/core/tests/mpkg_malformed.rs \
  pkg2mpkg/crates/fixtures/src
git commit -m "feat(pkg2mpkg): parse and validate MPKG containers"
~~~

---

### Task 5: Deterministic and Atomic MPKG Writer

**Files:**
- Create: pkg2mpkg/crates/core/src/mpkg/writer.rs
- Modify: pkg2mpkg/crates/core/src/mpkg/mod.rs
- Modify: pkg2mpkg/crates/core/src/error.rs
- Test: pkg2mpkg/crates/core/tests/mpkg_roundtrip.rs
- Test: pkg2mpkg/crates/core/tests/mpkg_atomic.rs

**Interfaces:**
- Produces: MpkgBuilder::new(version: ContainerVersion) -> MpkgBuilder
- Produces: MpkgBuilder::add_bytes(path, bytes) -> Result<()>
- Produces: MpkgBuilder::add_file(path, source) -> Result<()>
- Produces: MpkgBuilder::write_atomic(output, OverwritePolicy) -> Result<WriteReport>
- Consumes: ContainerVersion, MpkgArchive, and archive path validation from Task 4

- [ ] **Step 1: Write failing deterministic round-trip tests**

Write mpkg_roundtrip.rs:

~~~rust
use std::fs;
use pkg2mpkg_core::{ContainerVersion, MpkgArchive, MpkgBuilder, OverwritePolicy};
use tempfile::tempdir;

#[test]
fn writes_v20_in_insertion_order_and_round_trips() {
    let dir = tempdir().unwrap();
    let first = dir.path().join("first.mpkg");
    let second = dir.path().join("second.mpkg");
    for output in [&first, &second] {
        let mut builder = MpkgBuilder::new(ContainerVersion::Pkgm0020);
        builder.add_bytes("scene.json", br#"{"objects":[]}"#.to_vec()).unwrap();
        builder.add_bytes("project.json", br#"{"type":"scene"}"#.to_vec()).unwrap();
        builder.write_atomic(output, OverwritePolicy::Deny).unwrap();
    }
    assert_eq!(fs::read(&first).unwrap(), fs::read(&second).unwrap());
    let archive = MpkgArchive::open(&first).unwrap();
    assert_eq!(archive.entries()[0].path, "scene.json");
    assert_eq!(archive.entries()[1].path, "project.json");
}
~~~

- [ ] **Step 2: Write failing atomic-output tests**

Write mpkg_atomic.rs:

~~~rust
use std::{fs, fs::File};
use pkg2mpkg_core::{
    ContainerVersion, ErrorCode, MpkgBuilder, OverwritePolicy,
};
use tempfile::tempdir;

fn partials(dir: &std::path::Path) -> Vec<String> {
    fs::read_dir(dir)
        .unwrap()
        .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|name| name.ends_with(".partial"))
        .collect()
}

#[test]
fn deny_preserves_existing_output() {
    let dir = tempdir().unwrap();
    let output = dir.path().join("out.mpkg");
    fs::write(&output, b"original").unwrap();
    let mut builder = MpkgBuilder::new(ContainerVersion::Pkgm0020);
    builder.add_bytes("project.json", b"{}".to_vec()).unwrap();
    let error = builder.write_atomic(&output, OverwritePolicy::Deny).unwrap_err();
    assert_eq!(error.code(), ErrorCode::OutputIo);
    assert_eq!(fs::read(output).unwrap(), b"original");
    assert!(partials(dir.path()).is_empty());
}

#[test]
fn missing_source_leaves_no_output_or_partial() {
    let dir = tempdir().unwrap();
    let source = dir.path().join("scene.json");
    let output = dir.path().join("out.mpkg");
    fs::write(&source, b"{}").unwrap();
    let mut builder = MpkgBuilder::new(ContainerVersion::Pkgm0020);
    builder.add_file("scene.json", &source).unwrap();
    fs::remove_file(source).unwrap();
    assert!(builder.write_atomic(&output, OverwritePolicy::Deny).is_err());
    assert!(!output.exists());
    assert!(partials(dir.path()).is_empty());
}

#[test]
fn duplicate_is_rejected_before_writing() {
    let mut builder = MpkgBuilder::new(ContainerVersion::Pkgm0020);
    builder.add_bytes("a", vec![1]).unwrap();
    let error = builder.add_bytes("a", vec![2]).unwrap_err();
    assert_eq!(error.code(), ErrorCode::InvalidMpkg);
}

#[test]
fn four_gib_sparse_source_is_rejected_before_copy() {
    let dir = tempdir().unwrap();
    let source = dir.path().join("huge.bin");
    File::create(&source).unwrap().set_len(4 * 1024 * 1024 * 1024).unwrap();
    let output = dir.path().join("out.mpkg");
    let mut builder = MpkgBuilder::new(ContainerVersion::Pkgm0020);
    builder.add_file("huge.bin", &source).unwrap();
    let error = builder.write_atomic(&output, OverwritePolicy::Deny).unwrap_err();
    assert_eq!(error.code(), ErrorCode::PackageTooLarge);
    assert!(!output.exists());
}
~~~

The round-trip test from Step 1 also asserts successful writes leave no .partial sibling.

- [ ] **Step 3: Run tests and verify failure**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test mpkg_roundtrip --test mpkg_atomic
~~~

Expected: compilation fails because writer types do not exist.

- [ ] **Step 4: Implement ordered entry sources and checked layout**

Use:

~~~rust
enum EntrySource {
    Bytes(Vec<u8>),
    File { path: PathBuf, size: u64 },
}

struct PendingEntry {
    archive_path: String,
    source: EntrySource,
}

pub enum OverwritePolicy {
    Deny,
    Replace,
}

pub struct WriteReport {
    pub output: PathBuf,
    pub version: ContainerVersion,
    pub entries: usize,
    pub bytes: u64,
}
~~~

Store pending entries in Vec and a separate IndexMap for duplicate detection. Compute table and payload sizes using checked u64 arithmetic, then enforce every format field <= u32::MAX and total output < 4 * 1024 * 1024 * 1024.

- [ ] **Step 5: Implement same-directory atomic persistence**

Create the temporary file with a visible suffix so tests can detect cleanup:

~~~rust
let mut temp = tempfile::Builder::new()
    .prefix(".pkg2mpkg-")
    .suffix(".partial")
    .tempfile_in(parent)
    .map_err(|source| Error::Io {
        stage: Stage::Pack,
        path: parent.to_path_buf(),
        source,
    })?;
~~~

Write the header, ordered directory, and streamed payload through BufWriter. Flush, recover the File, call sync_all, reopen temp.path() through MpkgArchive, read every entry once, and compare entry sizes. Then persist:

~~~rust
match overwrite {
    OverwritePolicy::Deny => temp.persist_noclobber(output),
    OverwritePolicy::Replace => temp.persist(output),
}
.map_err(|error| Error::Io {
    stage: Stage::Pack,
    path: output.to_path_buf(),
    source: error.error,
})?;
~~~

Never delete the existing target before persist. tempfile's platform implementation performs the final rename; a failed replacement must leave the original target intact.

- [ ] **Step 6: Run focused tests, full tests, and clippy**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test mpkg_roundtrip --test mpkg_atomic
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
~~~

Expected: all commands pass.

- [ ] **Step 7: Commit Task 5**

Run:

~~~bash
git add pkg2mpkg/crates/core/src/mpkg pkg2mpkg/crates/core/src/error.rs \
  pkg2mpkg/crates/core/tests/mpkg_roundtrip.rs \
  pkg2mpkg/crates/core/tests/mpkg_atomic.rs
git commit -m "feat(pkg2mpkg): write MPKG files atomically"
~~~

---

### Task 6: Immutable ExportPlan and Backend Capability Contracts

**Files:**
- Create: pkg2mpkg/crates/core/src/backend.rs
- Create: pkg2mpkg/crates/core/src/export.rs
- Modify: pkg2mpkg/crates/core/src/lib.rs
- Modify: pkg2mpkg/crates/core/src/error.rs
- Test: pkg2mpkg/crates/core/tests/export_plan.rs

**Interfaces:**
- Produces: build_export_plan(source: &SourceProject, request: ExportRequest) -> Result<ExportPlan>
- Produces: BackendCapabilities::satisfies(&HelperRequirement) -> bool
- Consumes: SourceProject from Task 2 and Scene/profile/resolution types from Task 3

- [ ] **Step 1: Write failing Scene plan tests**

Write export_plan.rs:

~~~rust
use std::{fs, path::PathBuf};
use pkg2mpkg_core::{
    build_export_plan, inspect_source, ContentClass, ErrorCode, ExportMode,
    ExportRequest, HelperRequirement, ProjectManifest, SceneProfile, SourceProject,
    WallpaperKind,
};
use tempfile::{TempDir, tempdir};

fn synthetic_scene_source() -> (TempDir, SourceProject) {
    let dir = tempdir().unwrap();
    fs::write(dir.path().join("scene.json"), br#"{"camera":{},"objects":[]}"#).unwrap();
    fs::write(
        dir.path().join("project.json"),
        br#"{"title":"Fixture","type":"scene","file":"scene.json","properties":{"speed":{"value":1}}}"#,
    ).unwrap();
    let source = inspect_source(dir.path()).unwrap();
    (dir, source)
}

fn blocked_source(kind: WallpaperKind, entry: &str) -> SourceProject {
    let manifest_bytes = format!(
        r#"{{"title":"Blocked","type":"{}","file":"{entry}"}}"#,
        kind.as_str(),
    );
    SourceProject {
        root: PathBuf::from("fixture"),
        project_file: Some(PathBuf::from("fixture/project.json")),
        entry_file: PathBuf::from(entry),
        title: "Blocked".into(),
        kind,
        manifest: ProjectManifest::parse(manifest_bytes.as_bytes()).unwrap(),
    }
}

#[test]
fn balanced_scene_plan_requires_resource_transcoding_not_scene_capture() {
    let (_dir, source) = synthetic_scene_source();
    let plan = build_export_plan(
        &source,
        ExportRequest::scene(
            PathBuf::from("balanced.mpkg"),
            SceneProfile::Balanced,
            ContentClass::Normal,
        ),
    ).unwrap();
    assert_eq!(plan.kind, WallpaperKind::Scene);
    assert!(matches!(plan.mode, ExportMode::SceneDynamic { .. }));
    assert_eq!(plan.helpers, vec![HelperRequirement::ResourceTranscode]);
}

#[test]
fn performance_scene_plan_requires_capture_and_h264() {
    let (_dir, source) = synthetic_scene_source();
    let plan = build_export_plan(
        &source,
        ExportRequest::scene(
            PathBuf::from("performance.mpkg"),
            SceneProfile::Performance,
            ContentClass::Normal,
        ),
    ).unwrap();
    assert_eq!(plan.mode, ExportMode::ScenePreRenderedVideo);
    assert_eq!(
        plan.helpers,
        vec![HelperRequirement::SceneCapture, HelperRequirement::H264Encode]
    );
}

#[test]
fn plan_json_is_byte_stable() {
    let (_dir, source) = synthetic_scene_source();
    let request = ExportRequest::scene(
        PathBuf::from("stable.mpkg"),
        SceneProfile::High,
        ContentClass::PixelArt,
    );
    let first = serde_json::to_vec_pretty(&build_export_plan(&source, request.clone()).unwrap())
        .unwrap();
    let second = serde_json::to_vec_pretty(&build_export_plan(&source, request).unwrap())
        .unwrap();
    assert_eq!(first, second);
}

#[test]
fn builder_defensively_rejects_web_and_application() {
    for (kind, entry) in [
        (WallpaperKind::Web, "index.html"),
        (WallpaperKind::Application, "demo.exe"),
    ] {
        let source = blocked_source(kind, entry);
        let error = build_export_plan(
            &source,
            ExportRequest::scene(
                PathBuf::from("blocked.mpkg"),
                SceneProfile::Balanced,
                ContentClass::Normal,
            ),
        ).unwrap_err();
        assert_eq!(error.code(), ErrorCode::UnsupportedWallpaperType);
    }
}
~~~

- [ ] **Step 2: Write failing stable-JSON and unsupported-type tests**

The preceding test module includes both cases: it serializes the same request twice and constructs Web/Application `SourceProject` values directly to prove that `build_export_plan` preserves the type gate even though `inspect_source` normally blocks them.

- [ ] **Step 3: Run tests and verify failure**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test export_plan
~~~

Expected: compilation fails because export and backend contracts do not exist.

- [ ] **Step 4: Implement backend capability data only**

backend.rs defines no process launching:

~~~rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HelperRequirement {
    ResourceTranscode,
    SceneCapture,
    H264Encode,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BackendCapabilities {
    pub protocol_version: u32,
    pub requirements: Vec<HelperRequirement>,
}
~~~

Implement satisfies and missing_requirements using exact enum comparison.

- [ ] **Step 5: Implement immutable plans**

Use serde and IndexMap-backed deterministic collections:

~~~rust
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExportPlan {
    pub source: PathBuf,
    pub title: String,
    pub kind: WallpaperKind,
    pub mode: ExportMode,
    pub compatibility: CompatibilityTarget,
    pub properties: IndexMap<String, Value>,
    pub transformations: Vec<Transformation>,
    pub helpers: Vec<HelperRequirement>,
    pub estimated_size: Option<u64>,
    pub output: PathBuf,
}
~~~

Use these request and mode contracts so every choice is explicit and serializable:

~~~rust
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RequestedExportMode {
    Scene { profile: SceneProfile, content_class: ContentClass },
    Video { input: VideoInputCompatibility },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VideoInputCompatibility {
    Unknown,
    AndroidH264Mp4,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExportRequest {
    pub output: PathBuf,
    pub mode: RequestedExportMode,
}

impl ExportRequest {
    pub fn scene(output: PathBuf, profile: SceneProfile, content_class: ContentClass) -> Self;
    pub fn video(output: PathBuf, input: VideoInputCompatibility) -> Self;
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case")]
pub enum ExportMode {
    SceneDynamic { compression: Compression, reduction: Reduction },
    ScenePreRenderedVideo,
    Video { passthrough: bool },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "target", rename_all = "snake_case")]
pub enum CompatibilityTarget {
    WeAndroid { major: u8, minor: u8 },
}
~~~

`CompatibilityTarget` is fixed to `WeAndroid { major: 2, minor: 8 }` in this phase. Scene requests require an explicit profile. Video requests use `AndroidH264Mp4` only after the caller has verified codec/container compatibility; `Unknown` schedules H.264 encoding. A mismatched request/source kind returns `InvalidArguments`. The builder always rejects Web/Application before examining the requested mode.

The foundation builder plans work but does not execute helper requirements.

- [ ] **Step 6: Run tests and verify deterministic serialization**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg-core --test export_plan
cargo test -p pkg2mpkg-core
cargo clippy -p pkg2mpkg-core --all-targets -- -D warnings
~~~

Expected: all commands pass.

- [ ] **Step 7: Commit Task 6**

Run:

~~~bash
git add pkg2mpkg/crates/core/src/backend.rs pkg2mpkg/crates/core/src/export.rs \
  pkg2mpkg/crates/core/src/lib.rs pkg2mpkg/crates/core/src/error.rs \
  pkg2mpkg/crates/core/tests/export_plan.rs
git commit -m "feat(pkg2mpkg): build deterministic export plans"
~~~

---

### Task 7: CLI inspect, verify, and export --dry-run

**Files:**
- Modify: pkg2mpkg/crates/cli/Cargo.toml
- Replace: pkg2mpkg/crates/cli/src/main.rs
- Create: pkg2mpkg/crates/cli/src/args.rs
- Create: pkg2mpkg/crates/cli/src/output.rs
- Create: pkg2mpkg/crates/cli/src/commands/mod.rs
- Create: pkg2mpkg/crates/cli/src/commands/inspect.rs
- Create: pkg2mpkg/crates/cli/src/commands/verify.rs
- Create: pkg2mpkg/crates/cli/src/commands/export.rs
- Test: pkg2mpkg/crates/cli/tests/cli_inspect.rs
- Test: pkg2mpkg/crates/cli/tests/cli_verify.rs
- Test: pkg2mpkg/crates/cli/tests/cli_export_dry_run.rs
- Test: pkg2mpkg/crates/cli/tests/cli_error_codes.rs

**Interfaces:**
- Produces executable: pkg2mpkg
- Consumes inspect_source, build_export_plan, and MpkgArchive from Tasks 2, 4, and 6

- [ ] **Step 1: Write failing CLI inspect and error-code tests**

Use assert_cmd:

~~~rust
#[test]
fn inspect_scene_emits_machine_readable_json() {
    let project = synthetic_scene_project();
    let mut cmd = assert_cmd::cargo::cargo_bin_cmd!("pkg2mpkg");
    cmd.args(["inspect", project.path().to_str().unwrap(), "--json"])
        .assert()
        .success()
        .stdout(predicates::str::contains(r#""kind": "scene""#));
}

#[test]
fn web_returns_exit_code_three() {
    let project = synthetic_web_project();
    let mut cmd = assert_cmd::cargo::cargo_bin_cmd!("pkg2mpkg");
    cmd.args(["inspect", project.path().to_str().unwrap()])
        .assert()
        .code(3)
        .stderr(predicates::str::contains("unsupported wallpaper type"));
}
~~~

- [ ] **Step 2: Write failing verify and dry-run tests**

verify must print version, entry count, and project type for a valid synthetic package. export requires --profile for Scene and --dry-run in this foundation:

~~~rust
cmd.args([
    "export", project.path().to_str().unwrap(),
    "--output", output.to_str().unwrap(),
    "--profile", "balanced",
    "--dry-run",
    "--json",
])
.assert()
.success()
.stdout(predicates::str::contains(r#""scene_dynamic""#));
assert!(!output.exists());
~~~

Without --dry-run, assert exit code 5 and no output file.

- [ ] **Step 3: Run CLI tests and verify failure**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg --tests
~~~

Expected: tests fail because the command model is absent.

- [ ] **Step 4: Implement clap arguments**

Define:

~~~rust
#[derive(Parser)]
#[command(name = "pkg2mpkg", version, about)]
pub struct Args {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Subcommand)]
pub enum Command {
    Inspect { input: PathBuf, #[arg(long)] json: bool },
    Verify { input: PathBuf, #[arg(long)] json: bool },
    Export {
        input: PathBuf,
        #[arg(long)] output: PathBuf,
        #[arg(long, value_enum)] profile: Option<ProfileArg>,
        #[arg(long)] dry_run: bool,
        #[arg(long)] json: bool,
    },
}
~~~

ProfileArg values are high, balanced, performance. custom is introduced with its explicit compression/reduction flags in Plan 2.

- [ ] **Step 5: Implement thin commands and output**

inspect calls inspect_source and serializes a dedicated InspectOutput DTO. verify opens MpkgArchive, requires project.json, parses it through ProjectManifest, and rejects Web/Application packages. export builds ExportPlan; dry-run serializes it, while non-dry-run returns Error::BackendUnavailable { backend: "export executor" }.

Keep `main.rs` limited to parsing, dispatch, rendering an error, and mapping the stable exit code:

~~~rust
#![forbid(unsafe_code)]

mod args;
mod commands;
mod output;

use std::process::ExitCode;
use args::Args;
use clap::Parser;

fn main() -> ExitCode {
    let args = Args::parse();
    let json_errors = args.command.json();
    match commands::run(args.command) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            output::print_error(&error, json_errors);
            ExitCode::from(error.code().exit_code())
        }
    }
}
~~~

Add `Command::json(&self) -> bool` as a total match over all three variants. `commands::run` must also use a total match and delegate to functions with these exact signatures:

~~~rust
pub fn inspect(input: &Path, json: bool) -> Result<()>;
pub fn verify(input: &Path, json: bool) -> Result<()>;
pub fn export(
    input: &Path,
    output: PathBuf,
    profile: Option<ProfileArg>,
    dry_run: bool,
    json: bool,
) -> Result<()>;
~~~

`inspect` emits only a DTO containing root, entry file, title, kind, and raw manifest. `verify` emits only version magic, entry count, project type, and normalized entry names. `export` first calls `inspect_source`, then maps Scene plus a required profile to `ExportRequest::scene`; Video maps to `ExportRequest::video(output, VideoInputCompatibility::Unknown)` and rejects a Scene-only profile. It calls `build_export_plan` before checking `dry_run`, then returns `BackendUnavailable` for non-dry-run without opening or creating the output path. Human output goes to stdout, machine-readable errors go to stderr, and every JSON shape is represented by a serde DTO rather than assembled strings.

main returns ExitCode from ErrorCode::exit_code. --json errors serialize:

~~~json
{
  "code": "unsupported_wallpaper_type",
  "stage": "inspect",
  "message": "unsupported wallpaper type: web"
}
~~~

- [ ] **Step 6: Run CLI tests and manual smoke commands**

Run:

~~~bash
cd pkg2mpkg
cargo test -p pkg2mpkg --tests
cargo run -p pkg2mpkg -- --help
cargo run -p pkg2mpkg -- inspect ../research/Wallpaper\ Engine.2.8.26/projects/defaultprojects/dino_run --json
~~~

Expected: all tests pass; help lists inspect/verify/export; Dino Run reports kind scene without modifying the project.

- [ ] **Step 7: Commit Task 7**

Run:

~~~bash
git add pkg2mpkg/crates/cli
git commit -m "feat(pkg2mpkg): add inspect verify and dry-run CLI"
~~~

---

### Task 8: Synthetic Fixtures and Local Android Reference Check

**Files:**
- Create: pkg2mpkg/crates/fixtures/src/project.rs
- Modify: pkg2mpkg/crates/fixtures/src/lib.rs
- Create: pkg2mpkg/crates/fixtures/tests/reference_dino.rs
- Modify: pkg2mpkg/crates/core/tests/project_inspection.rs
- Modify: pkg2mpkg/crates/cli/tests/cli_inspect.rs
- Modify: pkg2mpkg/crates/cli/tests/cli_error_codes.rs
- Create: pkg2mpkg/reference/README.md

**Interfaces:**
- Produces: synthetic_scene_project(), synthetic_video_project(), synthetic_web_project(), synthetic_application_project()
- Consumes: MpkgArchive and ProjectManifest

- [ ] **Step 1: Move duplicated test setup into fixture helpers**

Implement project.rs with TempDir-owning SyntheticProject:

~~~rust
pub struct SyntheticProject {
    dir: tempfile::TempDir,
}

impl SyntheticProject {
    pub fn path(&self) -> &Path {
        self.dir.path()
    }
}

pub fn synthetic_scene_project() -> SyntheticProject;
pub fn synthetic_video_project() -> SyntheticProject;
pub fn synthetic_web_project() -> SyntheticProject;
pub fn synthetic_application_project() -> SyntheticProject;
~~~

Each helper writes only short original test content. Update existing tests to use these functions.

- [ ] **Step 2: Write the ignored local Dino reference test**

reference_dino.rs:

~~~rust
use std::{env, path::Path};
use pkg2mpkg_core::{MpkgArchive, ProjectManifest, WallpaperKind};

#[test]
#[ignore = "requires WE_DINO_MPKG extracted from the locally installed official APK"]
fn official_android_dino_is_v18_scene() {
    let path = env::var("WE_DINO_MPKG").expect("set WE_DINO_MPKG");
    let archive = MpkgArchive::open(Path::new(&path)).unwrap();
    assert_eq!(archive.version().as_magic(), "PKGM0018");
    let project = archive.read_entry("project.json").unwrap();
    let manifest = ProjectManifest::parse(&project).unwrap();
    assert_eq!(manifest.kind().unwrap(), WallpaperKind::Scene);
    assert_eq!(manifest.title(), Some("Dino Run"));
}
~~~

- [ ] **Step 3: Document the exact local reference procedure**

reference/README.md must state:

~~~bash
mkdir -p /tmp/pkg2mpkg-reference
unzip -p /path/to/io.wallpaperengine.weclient/base.apk \
  assets/wallpapers/dino_run.mpkg \
  > /tmp/pkg2mpkg-reference/dino_run.mpkg
WE_DINO_MPKG=/tmp/pkg2mpkg-reference/dino_run.mpkg \
  cargo test -p pkg2mpkg-fixtures --test reference_dino -- --ignored
~~~

State that the APK and extracted MPKG remain local and must never be added to git.

- [ ] **Step 4: Run all fixture and CLI tests**

Run:

~~~bash
cd pkg2mpkg
cargo test --workspace
~~~

Expected: all normal tests pass and reference_dino is reported ignored.

If /tmp/dino_run.mpkg from the prior read-only device inspection still exists, run:

~~~bash
cd pkg2mpkg
WE_DINO_MPKG=/tmp/dino_run.mpkg \
  cargo test -p pkg2mpkg-fixtures --test reference_dino -- --ignored
~~~

Expected: the local reference test passes.

- [ ] **Step 5: Commit Task 8**

Run:

~~~bash
git add pkg2mpkg/crates/fixtures pkg2mpkg/crates/core/tests \
  pkg2mpkg/crates/cli/tests pkg2mpkg/reference/README.md
git commit -m "test(pkg2mpkg): add synthetic and Android reference fixtures"
~~~

---

### Task 9: Foundation Documentation and Cross-Platform Quality Gate

**Files:**
- Create: pkg2mpkg/README.md
- Modify: .gitignore

**Interfaces:**
- Produces: documented foundation deliverable and reproducible verification commands
- Consumes: all earlier tasks

- [ ] **Step 1: Add only the required ignore rules**

Append:

~~~gitignore
# Rust pkg2mpkg build products and local reference fixtures
pkg2mpkg/target/
pkg2mpkg/reference/local/
~~~

Do not add broad rules that hide source, Cargo.lock, JSON fixtures, or plan files.

- [ ] **Step 2: Write README with exact supported behavior**

README sections:

- Evidence boundary and approved design link.
- Current commands: inspect, verify, export --dry-run.
- Supported input types and exact unsupported-type behavior.
- PKGM0018/0020 reader and synthetic writer status.
- Source files are read-only; actual dynamic/video conversion belongs to Plans 2 and 3.
- Build and test commands.
- Local Dino reference command.

Include:

~~~bash
cargo run -p pkg2mpkg -- inspect \
  "../research/Wallpaper Engine.2.8.26/projects/defaultprojects/dino_run" \
  --json

cargo run -p pkg2mpkg -- export /path/to/scene \
  --output /tmp/scene.mpkg \
  --profile balanced \
  --dry-run \
  --json

cargo run -p pkg2mpkg -- verify /path/to/wallpaper.mpkg --json
~~~

- [ ] **Step 3: Run the complete local gate**

Run:

~~~bash
cd pkg2mpkg
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo run -p pkg2mpkg -- --help
~~~

Expected: all commands exit 0.

- [ ] **Step 4: Check additional compilation targets**

Run:

~~~bash
rustup target add x86_64-unknown-linux-gnu x86_64-pc-windows-gnu
cd pkg2mpkg
cargo check --workspace --target x86_64-unknown-linux-gnu
cargo check --workspace --target x86_64-pc-windows-gnu
~~~

Expected: both cargo check commands pass. These crates are pure Rust and do not require linking external native helpers in this plan.

- [ ] **Step 5: Verify repository hygiene**

Run:

~~~bash
git status --short
git ls-files pkg2mpkg | rg '\.(apk|dll|exe|mpkg)$' && exit 1 || true
git diff --check
~~~

Expected: only intended plan implementation changes are present; no proprietary binaries or whitespace errors are tracked.

- [ ] **Step 6: Commit Task 9**

Run:

~~~bash
git add .gitignore pkg2mpkg/README.md
git commit -m "docs(pkg2mpkg): document foundation workflow"
~~~

## Foundation Acceptance Checklist

- [ ] pkg2mpkg-core, pkg2mpkg-fixtures, and pkg2mpkg compile with #![forbid(unsafe_code)].
- [ ] inspect identifies Scene and Video without modifying inputs.
- [ ] inspect rejects explicit or inferred Web/Application with exit code 3.
- [ ] property sanitization matches the Windows 2.8.26 blacklist.
- [ ] High Quality, Balanced, and Performance resolve to the approved modes.
- [ ] 1920 × 1080 landscape geometry remains landscape.
- [ ] KeepAspect does not add padding; Cover returns the exact target canvas.
- [ ] MPKG reader accepts synthetic PKGM0018/PKGM0020.
- [ ] MPKG reader rejects every listed malformed container class.
- [ ] writer is deterministic, self-verifying, atomic, and bounded below 4 GiB.
- [ ] export --dry-run emits stable ExportPlan JSON and never creates output.
- [ ] verify reads project.json and rejects Web/Application packages.
- [ ] local official Dino Run verifies as PKGM0018 type scene when explicitly enabled.
- [ ] fmt, clippy -D warnings, workspace tests, Linux check, and Windows check pass.
- [ ] no official binary or wallpaper asset is tracked.

## Next Plan Entry Condition

Write the Dynamic Scene implementation plan only after this checklist passes. Its interfaces must consume SourceProject, ExportPlan, MpkgArchive, MpkgBuilder, ResourceTranscode capability contracts, and the exact errors implemented here; it must not redefine them.
