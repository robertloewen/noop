# CLAUDE.local.md: working rules for this fork (robertloewen/noop)

Read together with CLAUDE.md / AGENTS.md (upstream rules still apply). This file exists only in the
fork and is not part of upstream.

## The user and the workflow

- Talk to the user in **German**. Repository text (commits, code comments, docs other than
  ENTWICKLUNGSPLAN.md) stays in English, as AGENTS.md requires.
- The user describes changes; you make them end to end: edit, check, commit, **push without asking**,
  and build onto the iPhone when the change affects the app.
- Read `ENTWICKLUNGSPLAN.md` at the start of a session. Tick off finished items and add findings
  under the matching phase.

## Git

- Work on the branch **`custom`** only. Never commit to `main`: it mirrors ryanbr/noop and the
  `Upstream sync` workflow fast-forwards it daily.
- Before starting: `git pull --rebase origin custom`.
- After every finished change: run the relevant checks (below), commit with a summary of at most
  72 characters plus a short description, then `git push origin custom`. Tell the user the commit.
- Never commit health data, exports or tokens (`research/data/`, `*.sqlite`, `*.zip`, `.env`,
  `Config/BundleIdSecrets.xcconfig`). Check `git status` before committing.
- Prefer new files over edits to upstream files, to keep the daily upstream sync conflict-free.

## Build and install on the iPhone

- Regenerate the Xcode project with `Tools/fork/generate-ios.sh`, never plain `xcodegen generate`
  (the free Apple ID cannot sign the embedded watch app).
- Build and install in one step: `Tools/fork/install-ios.sh "<device>"`. Find the device name once
  with `xcrun devicectl list devices` and reuse it. The iPhone must be on the same Wi-Fi (or cabled)
  and unlocked.
- A build failure is a failed change: fix it before committing, or say clearly what is broken.

## Checks

- Swift packages: `cd Packages/<Pkg> && swift test`.
- Research code: `python3 -m unittest discover -s research/tests -t .`
- App code (`Strand/`, `StrandiOS*/`): the iPhone build above is the check.

## Design direction (Phase 7)

- Target look: WHOOP style. Dark mode in two variants the user picks in Settings, **WHOOP Dark**
  and **WHOOP AMOLED** (true black). The system light/dark setting is followed; light mode uses
  NOOP's light look with the WHOOP accent colours.
- Colours measured from the user's WHOOP screenshots (WHOOP Dark):
  background gradient #293137 → #1D2227 → #0E1012; card #2F3337; row in card #424649; button #3D4041;
  date pill #31383E / #454C51; text #FFFFFF / #A0A2A4 / #8E9193; sleep #83A0B8; recovery green
  #6EE846, yellow #F9DF4A, red #EA3334; strain/activity blue #4090E0; ring track #373D41;
  stress #77ACE1; alarm green #6EEDA5; tab bar #23292F.
- AMOLED: background #000000, card #15181B, row #26292C, button #222528, ring track #24282B;
  text and accent colours unchanged.
- Home screen order like WHOOP: three rings (Schlaf, Erholung, Belastung) → Gesundheitsmonitor |
  Stress-Monitor → Mein Tag (daily outlook, activities) → Schlaf für heute Nacht → Mein Dashboard.
- Colours go into the design tokens (`Packages/StrandDesign`), never hard-coded in screens.
