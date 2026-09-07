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

Attribution
-----------

Based on BeeRef by Rebecca Breu and contributors. Original copyright notices
and the GNU GPL license are preserved in the source and ``LICENSE``.
