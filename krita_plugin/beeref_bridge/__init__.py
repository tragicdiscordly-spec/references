"""Krita plugin entry point for the BeeRef zoom bridge."""

from krita import Krita

from .beeref_bridge import BeeRefBridgeExtension


app = Krita.instance()
app.addExtension(BeeRefBridgeExtension(app))
