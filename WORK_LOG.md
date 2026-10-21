# STARK work history

**STARK — Spatial Tracking and Recognition Kit**  
Repository: [KennyBHRepo/DEX](https://github.com/KennyBHRepo/DEX)

**Summary recorded:** October 20, 2026 at 9:20:19 PM EDT (`2026-10-20T21:20:19-04:00`).

All timestamps below use **America/New_York**. Exact times are included when recorded in Git or a local installation backup. Earlier milestones have date-only entries because their exact completion times were not recorded. Installation backup times indicate when an update was applied, not when development began or ended.

## Current result

STARK is a native macOS interface around the original HandControl gesture engine. It includes a large camera preview, floating mini preview, guided practice, configurable game-style controls, settings, menu-bar controls, a global toggle, multi-display pointer mapping, optional double-clap activation, and the STARK liquid-glass visual identity.

The source, logo, app builder, installation scripts, documentation and tests are published here. The generated `.app` is a local launcher that depends on the source folder and Python environment; it is not a portable, notarized application bundle.

## October 4, 2026 — Native desktop experience

* Replaced the terminal-oriented experience with a native AppKit interface while retaining the camera preview and underlying gesture/input engine.
* Added clear live state and gesture feedback, camera/gesture controls, settings and a guided walkthrough that practices without sending real mouse or keyboard input.
* Added a menu-bar control and **Control–Option–M** global toggle. Turning gestures off releases the camera; closing a preview stops gesture control.
* Added a game-style Controls screen covering gesture mappings, exact shortcut inputs, shortcut recording, search, restore defaults and immediate application of saved changes.
* Added configurable pointer hand, camera, pointer feel, scrolling, dictation and fine-tuning controls.
* Improved Accessibility permission guidance, waiting for permission, and recovery from a stale permission entry.
* Created a native app launcher, icon generation/build process, launch scripts, documentation and regression checks.
* Developed the initial branding and then named the app **Dex**. STARK superseded that name on October 20.

## October 9, 2026 — Sharing preparation

* Prepared a clean source package and fresh-install instructions for sharing.
* Excluded local virtual environments, logs, backups and machine-specific app bundles from the publication package.
* Confirmed that friends need to build a launcher on their own Mac rather than copy an existing machine-bound `.app`.
* Publication was not completed during this session. The first successful repository publication is recorded below on October 20.

## October 19, 2026 — Control and workflow improvements

* Extended pointer mapping from the primary display to the combined desktop, including negative screen origins and gaps between displays. Added layout refresh during use.
* Added a small floating **Mini preview** with Start/Stop, Expand and Settings, positioned initially in the lower-right corner and movable by its title bar.
* Corrected camera enumeration to match OpenCV's device-ID ordering. Saved explicit camera choices by stable identity, preferred the laptop/webcam in automatic mode, and made phone-camera selection explicit.
* Added optional **double-clap wake**, using a native in-process microphone meter and a paired-transient detector. Audio is not saved or uploaded. Listening pauses during active gesture control, onboarding and editing.
* Added microphone permission text and a visible listening indicator. Clap activation still uses the normal camera and Accessibility permission checks.
* Added a gesture guard requiring deliberate open-palm arming, rejecting tracking jumps and lost-hand re-entry, and requiring an 80 ms pinch confirmation.
* Preserved the user's existing mappings and tuning, backed up the previous installation, and rebuilt the app.
* Read-only hardware verification detected two displays as a **3328 × 1080** combined pointer area and selected the built-in laptop camera automatically.
* Validation at this milestone: **103 automated checks and 28 native UI checks passed**. Actual clap sensitivity and pointer feel were left for hands-on evaluation.

### October 19, 2026 at 4:57:11 PM EDT — Face-overlap correction

Installation backup timestamp: `2026-10-19T16:57:11-04:00`.

* User feedback showed that the first face guard paused control when a hand passed in front of the face, even without touching it.
* Removed the face-overlap pause and its runtime face-detector work. A 2-D image overlap was not a reliable measure of contact or distance.
* Kept deliberate arming, tracking-jump protection and pinch confirmation.
* Updated the Settings wording, documentation and regression test to reflect the corrected behavior.
* **22 targeted checks passed**; installed the patch and restarted the app while preserving settings and clap wake.

## October 20, 2026 at 5:48:55 PM EDT — STARK rebrand installed

Installation backup timestamp: `2026-10-20T17:48:55-04:00`.

* Renamed the visible app, menus, onboarding, settings, mini preview, installer and documentation to **STARK**.
* Replaced the previous logo with the supplied neon liquid-glass cursor artwork.
* Applied a quieter matching interface: midnight-navy surfaces, subtle violet borders, cyan feedback and restrained blue action buttons.
* Updated the Desktop application and Dock entry; retained a backup of the Dex installation.
* Preserved the gesture engine, configuration and existing internal app identity for continuity with macOS permissions and welcome preferences.
* **103 automated checks and 28 native UI checks passed**; opened the installed app and visually checked the interface.

## October 20, 2026 at 7:13:29 PM EDT — First GitHub publication

Git timestamp: `2026-10-20T19:13:29-04:00`.  
Commit: [`bf09f85`](https://github.com/KennyBHRepo/DEX/commit/bf09f85162ef0daff2d1f3b690f234940d05e39f).

* Published **31 files** to `main`: app source, logo, native audio helper, configuration defaults, tests, documentation and setup/build scripts.
* Added a fresh-install script that creates a virtual environment, installs dependencies, runs the checks and builds `STARK.app` on the recipient's Desktop.
* Documented prerequisites, permissions, first-use model download and the relationship between the app launcher and source folder.
* Included starter settings rather than the user's personal configuration. Excluded local environments, logs, backups and generated app bundles.
* **103 automated checks passed** against the publishable package. Verified the remote commit and repository contents after pushing.

## October 20, 2026 at 8:55:55 PM EDT — Tighter logo framing

Git timestamp: `2026-10-20T20:55:55-04:00`.  
Commit: [`d39c28a`](https://github.com/KennyBHRepo/DEX/commit/d39c28a).

* Reduced the logo's outer black margins to approximately one quarter of their earlier width, retaining the liquid-glass cursor design and full glowing outline.
* Updated the source asset, rebuilt the installed application icon and published the new artwork.
* This was an asset-only change; no gesture behavior was changed.

## October 20, 2026 at 9:11:42 PM EDT — Full name established

Git timestamp: `2026-10-20T21:11:42-04:00`.  
Commit: [`d4ee771`](https://github.com/KennyBHRepo/DEX/commit/d4ee771).

* Defined the name as **Spatial Tracking and Recognition Kit**.
* Added the expansion to the app subtitle, About text, README and design notes.
* Updated the installed source and published the documentation/code change. Checked Python syntax; the running app picks up the text on reopening.

## Validation scope and remaining limits

* Automated checks cover gesture logic, control mappings, settings persistence, session lifecycle, camera selection, display geometry, guard behavior and clap timing.
* The native UI self-check opens and exercises the interface without opening the camera, listening to the microphone or moving the real pointer.
* Hardware enumeration verifies the detected devices and display geometry, not end-to-end pointer accuracy on every display.
* Double-clap wake requires the app to remain running and Microphone permission. It cannot start a fully quit app or wake a sleeping Mac; similar transient sounds can trigger it.
* The current guard does **not** claim to detect hand-to-face contact or measure absolute depth.
* Camera, microphone, recognition accuracy and input feel depend on the user's environment and need hands-on evaluation. Installation has not been verified across every supported Python/macOS/architecture combination.
