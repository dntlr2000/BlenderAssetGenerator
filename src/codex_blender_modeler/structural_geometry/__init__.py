"""Strict structural-geometry contracts and deterministic mesh helpers.

The package intentionally avoids eager imports. Blender's bundled Python can import the
pure-stdlib mesh compiler without also importing host-only Pydantic contracts.
"""
