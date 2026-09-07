# BeeRef project guide

## Confirmed working checkpoint — 2026-09-07

The user manually verified that canvas panning and zooming stay aligned after
the cross-process DPI conversion fix. Krita reports DPR 1.0 and BeeRef DPR 1.25
on this Windows setup. Preserve that conversion for both canvas geometry and
all six matrix coefficients, and subtract the rounded overlay window origin
when painting. The full offscreen suite passed: 1,055 tests. The prior nested
plugin installation was also corrected; use the installer below for updates.

## Purpose

This repository is being adapted into a Windows tracing overlay for Krita.
The user places a reference image in BeeRef, pins it over the Krita canvas,
and draws in Krita underneath it.

The pinned reference must:

- stay aligned when the Krita window moves or is resized;
- follow Krita canvas panning and zooming without cumulative drift;
- remain click-through while locked so brush and middle-mouse input reaches
  Krita;
- stay out of OBS and normal screen captures;
- avoid a visible Python taskbar application. BeeRef uses a tray-only,
  taskbar-hidden window. It must not impersonate Discord.

## Important files

- beeref/__main__.py: transparent always-on-top window, tray behavior, global
  hotkeys, OBS exclusion, and Windows input pass-through.
- beeref/clipstudio.py: Krita/Clip Studio window detection, native window
  following, bridge polling, zoom, and canvas-pan tracking.
- krita_plugin/beeref_bridge/beeref_bridge.py: Krita plugin that publishes
  zoom, preferred canvas center, rotation, cursor position, and Krita HWND.
- krita_plugin/kritapykrita_beeref_bridge.desktop: Krita plugin metadata.
- BeeRef-hidden.vbs: starts BeeRef without a console window.
- BeeRef-hidden.cmd: launcher that searches for installed Python versions.

## Running BeeRef on Windows

Run this file from the repository folder:

    .\BeeRef-hidden.vbs

The launcher searches Python 3.12, 3.11, and 3.10, then pyw.exe, py.exe,
and Python on PATH. Do not hard-code python310; that was the original
launcher failure.

## Krita bridge setup

The plugin is installed under:

    %APPDATA%\krita\pykrita\beeref_bridge

Enable BeeRef Zoom Bridge in Krita's Python Plugin Manager, then restart
Krita if the plugin was newly installed or changed. The bridge writes:

    %LOCALAPPDATA%\BeeRef\clipstudio_transform.json

Install updates using `powershell -ExecutionPolicy Bypass -File
.\krita_plugin\install-bridge.ps1` from the repository root. It preserves the
old plugin outside the import path and prevents a nested beeref_bridge package
from shadowing the new Python file. Verify `bridge_build`, `bridge_source`,
and `pid` in the JSON, not only the installed file hash: an older nested package
previously loaded despite the correct file being present on disk.

Krita and BeeRef can use different Qt device pixel ratios (observed: Krita
1.0, BeeRef 1.25 on a 5120x1440 Windows desktop). Never treat their desktop
coordinates as interchangeable. BeeRef scales canvas rectangles and matrix
coefficients by Krita DPR / BeeRef DPR, about the monitor origin, before
establishing or updating the lock. Build 3.2 publishes screen identity/origin
for multi-monitor matching; build 3.1 works on a single monitor using its DPR.

BeeRef uses the bridge when available and falls back to native window-follow
tracking and title/status zoom detection when it is unavailable.
The current bridge publishes a protocol-3 state with the Krita canvas widget
rectangle in Qt desktop coordinates. While locked, BeeRef renders the image in
a dedicated canvas-sized, capture-excluded window. That window converts the
saved image placement to document coordinates once, then applies the current
absolute document-to-canvas transform on every update; it does not accumulate
zoom/pan deltas or move a QGraphics clone around the desktop. The bridge and
BeeRef poll at roughly 30 ms; the bridge writes atomically without forcing a
disk flush on every interactive update. Protocol 3 uses image-pixel coordinates
from flakeToImageTransform (not physical document units), labels the matrix
space as `image`, and includes an idle heartbeat every 0.5 seconds. BeeRef
rejects protocol-3 data older than two seconds and requires the exact matrix
for modern locks; legacy matrix and zoom/center payloads remain readable.
Restart both apps after updating the bridge. Headless tests can be run with
`$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q` without inspecting or
controlling the user's Krita canvas.

## Hotkeys

- Ctrl+T: attach and lock the selected image; press again to unlock.
- Ctrl+Shift+R: resync the current image position.
- Ctrl+Shift+U: detach the pin.

## Validation

Compile the Python sources:

    python -m compileall -q beeref krita_plugin

Run the test suite:

    pytest -q

When testing alignment, use a saved or disposable Krita document. Verify in
this order: lock, draw through the overlay, move the Krita window, pan the
canvas, zoom around different cursor locations, resize Krita, then unlock
and relock after manually moving the reference.
While locked, the editable BeeRef item is hidden and a non-interactive proxy
is rendered only inside the reported Krita canvas rectangle. Unlocking restores
the original item without changing its saved position. If the bridge cannot
expose the canvas widget, the locked proxy stays hidden instead of covering
Krita docks or other windows.

## Image inspection for coding agents

OBS exclusion only affects capture of the BeeRef window. It does not mean the
project's image files are unavailable. When visual inspection is needed, use
the local image viewer/tooling on an absolute file path, or open the image in
the Codex workspace panel. Do not infer that an image is missing merely
because it is excluded from OBS.

## Change discipline

Keep the bridge protocol backward-compatible with existing matrix payloads
and the current zoom/center payload. Preserve the taskbar-hidden and OBS
exclusion behavior. After changes to tracking math, run focused tests and the
full suite before asking the user to retest.
