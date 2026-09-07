# Krita / Clip Studio canvas pinning

Place a selected image over Krita or Clip Studio Paint, then press `Ctrl+T`.
BeeRef saves its current position, follows the paint window's movement and
resize, and becomes click-through. Press `Ctrl+T` again to unlock and edit.

The locked tracing overlay requires the Krita bridge's canvas rectangle and
transform. Without complete data it stays hidden and waits. Native window
and title/status zoom tracking are only a legacy fallback for the editable
image; they cannot provide an accurate locked tracing reference.

While unlocked, drag the image into a new position and press `Ctrl+T` again to
save that position and lock it. `Ctrl+Shift+R` saves the current position
without changing lock state, and `Ctrl+Shift+U` detaches the pin.

When locked with the Krita bridge active, BeeRef renders a non-interactive
proxy of the reference only inside Krita's canvas widget. Zooming, panning,
rotation, window movement, and resize are applied from the current absolute
canvas state relative to the lock baseline, so small polling errors do not
accumulate into drift.

## Optional transform bridge

If a local Clip Studio helper/plugin is available, it can write this file:

`%LOCALAPPDATA%\\BeeRef\\clipstudio_transform.json`

```json
{"matrix": [a, b, c, d, tx, ty]}
```

The six values are an affine canvas matrix. The Krita bridge additionally
publishes zoom, preferred center, rotation, and the canvas-widget rectangle in
Qt desktop coordinates. BeeRef polls the file locally and applies one absolute
transform relative to the lock baseline. The current protocol 3 labels that
matrix's coordinates as `image`, includes a timestamp, and sends an idle
heartbeat. Missing, invalid or expired modern data hides the locked overlay.
Restart both apps after installing an updated bridge, then unlock/relock the
reference to establish a fresh alignment.
