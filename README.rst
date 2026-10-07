References
==========

A personal Windows tracing overlay for Krita.

Place a reference over your drawing, adjust opacity or grayscale, and lock it
in place. The reference follows canvas panning and zooming while pen and mouse
input passes through to Krita.

Setup
-----

Install Python 3.10, 3.11 or 3.12, then install References' dependencies from
this folder::

    py -3.12 -m pip install -e .

The Krita plugin installer is ``krita_plugin/install-bridge.ps1``. See
``krita_plugin/README.md`` for setup. Existing launcher and internal module names
remain compatible with saved settings and plugin installations.

Running
-------

Launch ``BeeRef-hidden.vbs`` from this folder. Right-click the overlay or
click the purple tray icon for the controls. Use the File menu to add images
or open and save reference boards. The Images menu contains opacity and
grayscale.

* ``Ctrl+T``: pin the selected reference, or unpin it to edit it. A pinned
  reference is click-through. Over Krita or Clip Studio it follows the
  canvas as you pan and zoom; over any other window it stays where it is.
* ``Ctrl+Shift+R``: resync the reference placement.
* ``Ctrl+Shift+U``: detach the reference and make it editable again.

The overlay covers every monitor except the taskbar, so Windows never treats
it as a full-screen app.

Sending an image from your phone
--------------------------------

One-time setup:

1. Download ``cloudflared.exe``, Cloudflare Tunnel's Windows client, and save
   it as ``%LOCALAPPDATA%\References\cloudflared.exe``. A ``cloudflared`` on
   ``PATH`` or a path in the ``REFERENCES_CLOUDFLARED`` environment variable
   also works.
2. Run ``powershell -ExecutionPolicy Bypass -File .\Set-phone-login.ps1`` and
   choose the username and password your phone will log in with. Only a
   salted hash of the password is saved, in
   ``%LOCALAPPDATA%\References\phone-login.json`` and the git-ignored
   ``.private`` folder. Run it again to change the login.

Then right-click the unlocked overlay and select ``Send image from phone…``.
References starts a temporary Cloudflare link and shows it in the panel.
Open the link on your phone (any network works, including mobile data or a
VPN on the PC), log in, choose a photo and tap ``Send to PC``. You can leave
References locked and continue drawing in Krita. No app opens on the PC when
an upload arrives. If the panel says the receiver could not start, it names
the missing setup step.

An upload replaces the locked or selected reference, or the only image if
there is just one. Otherwise it adds a new reference. Replacements keep their
center, fit within the old reference's bounds, and preserve opacity/grayscale.
Unlock and use Undo to restore the previous image. Saving the board saves the
replacement.

Privacy: the receiver only listens on your PC, and the phone reaches it
through a Cloudflare Quick Tunnel. The connection is encrypted on both sides,
but Cloudflare decrypts it in between, so uploaded images pass through
Cloudflare's servers. References itself keeps uploads only in memory. The
link contains a secret token and the login is required as well; keep both
private. A login lasts one hour. The link changes each time the receiver
starts, and it stops when you press ``Stop phone receiving`` or quit
References.

The limit is 20 MB and 40 megapixels; JPEG, PNG and WebP are supported by the
installed image readers. Convert HEIC to JPEG if your phone's file is rejected.

The right-click controls, including the opacity slider, are child widgets of
the protected overlay rather than separate popup windows. Escape or a click
outside the panel on an image closes it. Empty space remains click-through
so other apps stay accessible even while editing. Ctrl+T also makes the
reference itself click-through for tracing.

Development
-----------

Run the tests and linter from this folder::

    py -3.12 -m pip install -r requirements/test.txt flake8==7.0.0
    $env:QT_QPA_PLATFORM='offscreen'; py -3.12 -m pytest -q
    py -3.12 -m flake8 .

GitHub Actions runs the same checks on every push. ``agent.md`` describes
the tracking design and the rules to keep when changing it.

Attribution
-----------

Based on BeeRef by Rebecca Breu and contributors. Original copyright notices
and the GNU GPL license are preserved in the source and ``LICENSE``.
