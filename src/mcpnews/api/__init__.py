"""The JSON API the dashboard consumes.

Errors and notes are catalogue keys, never sentences: the browser knows the
reader's language and this layer does not.
"""
from mcpnews.api.app import create_app

__all__ = ["create_app"]
