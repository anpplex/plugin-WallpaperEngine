# WE 车机独立仓库 Bootstrap · Implementation Plan

> **For agentic workers:** Use subagent-driven-development or executing-plans task-by-task.

**Goal:** Standalone git repo for WE car adaptation with buildable app baseline.

**Architecture:** Single-module Android app + we-official patch docs + superpowers docs.

**Tech Stack:** Kotlin, Compose, AGP 8.7.3, Gradle Wrapper.

## Global Constraints

- applicationId `com.motif.wallpaperengine`
- No commit of `*.apk` / `*.mpkg` / full apktool trees
- Branch naming `we-car/*`
- JAVA_HOME JDK 17

---

### Task 1: Repository bootstrap (this plan)

**Files:**
- Create: repo root Gradle, `.gitignore`, `README.md`, `app/`, `docs/`, `scripts/`, `we-official/`

- [x] Step 1: Scaffold from Motif WallpaperEngine sources  
- [x] Step 2: Standalone Gradle (`:app`)  
- [x] Step 3: Docs + gitignore + design/plan  
- [ ] Step 4: `git init` + initial commit on `main`  
- [ ] Step 5: Verify `./gradlew :app:assembleDebug`  

### Task 2 (next): Import/library polish on branch

**Branch:** `we-car/library-sync`

- [ ] Harden batch import + onNewIntent  
- [ ] Official patch rebuild script  
- [ ] Real-car checklist update  

---
