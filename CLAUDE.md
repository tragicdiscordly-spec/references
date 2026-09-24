# CLAUDE.md

References is a personal Windows tracing overlay for Krita, built on a fork of
BeeRef (Python, PyQt6). The user pins a reference image over the Krita canvas
and draws underneath it; the image follows Krita's pan and zoom, lets pen
input through, and stays out of OBS captures.

The full project guide is `agent.md`, which other coding agents also read
through `AGENTS.md`. It is imported here; keep it the single source of truth
and update it when behavior or workflow changes.

@agent.md

## Commands

```sh
pip install -e . -r requirements/test.txt flake8==7.0.0
QT_QPA_PLATFORM=offscreen pytest -q                               # full suite, ~20 s
QT_QPA_PLATFORM=offscreen pytest -q tests/test_phone_receiver.py  # one file
flake8 .                                                          # 79 columns, enforced in CI
python -m compileall -q beeref krita_plugin
```

In a bare Linux container Qt also needs system libraries:
`apt-get install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`.
Running as root makes five read-only-file tests fail; that is expected.

## Code map

Upstream BeeRef code (`items.py`, `scene.py`, `view.py`, `fileio/`, `widgets/`)
is mostly unchanged. The References additions:

- `beeref/__main__.py`: transparent always-on-top window, tray icon, global
  hotkeys, capture exclusion, click-through, phone receiver start/stop.
- `beeref/clipstudio.py`: Krita window detection and bridge polling
  (`LocalTransformBridge`), pin/lock controller, DPI conversion.
- `beeref/locked_overlay.py`: the canvas-sized window that draws the locked
  reference from the absolute Krita transform.
- `beeref/reference_controls.py`: the embedded right-click/tray panel.
- `beeref/phone_receiver.py`: loopback HTTP inbox, login, Cloudflare tunnel.
- `beeref/replace_reference.py`: undoable image replacement from the phone.
- `krita_plugin/`: the Krita side of the bridge and its installer.
- `BeeRef-hidden.vbs`/`.cmd`, `Set-phone-login.ps1`: Windows launchers/setup.

## Working rules

- This container is not Windows and has no Krita or OBS. Windows-only paths
  (`platform.system() == 'Windows'`, `user32` calls) run here only through
  mocks. Never claim capture exclusion, click-through or canvas alignment
  works from offscreen tests; say what the user should check on their PC,
  in the order `agent.md` gives.
- User-facing text says "References". Keep internal BeeRef names, settings
  paths and the `%LOCALAPPDATA%\BeeRef` bridge file for compatibility.
- The Krita plugin and the app update separately: keep the bridge JSON
  backward-compatible.
- Never log or commit pairing tokens, `phone-login.json`, `.private/`, or
  uploaded images.
- Tests are plain pytest functions next to the matching module's tests,
  using fixtures from `tests/conftest.py` (`qapp`, `main_window`, `view`,
  `item`, `tmpfile`). Add a test that fails without each fix.
