# BeeRef Krita zoom bridge

Run `powershell -ExecutionPolicy Bypass -File .\krita_plugin\install-bridge.ps1`
from the repository root. It backs up any existing installation outside Krita's
plugin path and installs the files without nested duplicate packages. Enable
BeeRef Zoom Bridge in Krita's Python Plugin Manager and restart Krita.

The plugin publishes Krita's actual canvas zoom, preferred center, rotation,
and canvas-widget rectangle to
%LOCALAPPDATA%\\BeeRef\\clipstudio_transform.json. The rectangle is in Qt
desktop coordinates so BeeRef can clip the reference to the canvas itself.
BeeRef consumes that file while a reference is pinned.

Protocol 3 also publishes the exact image-pixel-to-canvas matrix, labelled
`view_matrix_space: image`, and a timestamp heartbeat every half second.
BeeRef uses that absolute mapping for locking rather than estimating pan
from the preferred center. Restart Krita and BeeRef after updating the plugin.

The JSON includes `bridge_build`, `bridge_source`, and `pid` so the loaded
implementation can be verified without screenshots. A healthy current bridge
reports protocol 3, build `image-transform-3.2`, and matrix space `image`.
Do not copy the source folder inside the installed beeref_bridge folder:
a nested package named beeref_bridge takes precedence over beeref_bridge.py.

Build 3.2 adds the canvas screen name and origin alongside its device pixel
ratio. BeeRef converts these coordinates to its own Qt scaling before drawing;
the two apps need not have the same DPI settings. Build 3.1's DPR field remains
sufficient on a single-monitor desktop.
