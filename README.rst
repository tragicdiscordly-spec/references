References
==========

A personal Windows tracing overlay for Krita.

Place a reference over your drawing, adjust opacity or grayscale, and lock it
in place. The reference follows canvas panning and zooming while pen and mouse
input passes through to Krita.

Running
-------

Launch ``BeeRef-hidden.vbs`` from this folder. Use the File menu to add images
or open and save reference boards. The Images menu contains opacity and grayscale.

* ``Ctrl+T``: lock or unlock the selected reference.
* ``Ctrl+Shift+R``: resync the reference placement.
* ``Ctrl+Shift+U``: detach the reference.

The Krita plugin installer is ``krita_plugin/install-bridge.ps1``. See
``krita_plugin/README.md`` for setup. Existing launcher and internal module names
remain compatible with saved settings and plugin installations.

Sending an image from your phone
-------------------------------

Right-click the unlocked overlay and select ``Send image from phone…``.
This starts a local receiver and displays a private pairing link. Open that
link in your phone's browser on the same Wi-Fi, choose a photo, and tap
``Send to PC``. You can leave References locked and continue drawing in Krita.
No app opens on the PC when an upload arrives.

An upload replaces the locked or selected reference, or the only image if
there is just one. Otherwise it adds a new reference. Replacements keep their
center, fit within the old reference's bounds, and preserve opacity/grayscale.
Unlock and use Undo to restore the previous image.

Uploads stay in memory on your PC; no cloud service is used. The link contains
a secret token: keep it private and use a trusted home network. If Windows
asks about Python network access, allow it on your private network only.
Guest Wi-Fi/client isolation can prevent the phone from reaching the PC.
The limit is 20 MB and 40 megapixels; JPEG, PNG and WebP are supported by the
installed image readers. Convert HEIC to JPEG if your phone's file is rejected.
Stop receiving from the pairing panel when finished. Restarting the receiver
creates a new link; bookmark it for the current session.

The right-click controls, including the opacity slider, are child widgets of
the protected overlay rather than separate popup windows. Escape or a click
outside the panel on an image closes it. Empty space remains click-through
so other apps stay accessible even while editing. Ctrl+T also makes the
reference itself click-through for tracing.

Attribution
-----------

Based on BeeRef by Rebecca Breu and contributors. Original copyright notices
and the GNU GPL license are preserved in the source and ``LICENSE``.
