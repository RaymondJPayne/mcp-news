"""Article storage. SQLite by default, adapters for larger backends.

The interface lives in ``base.py`` and is deliberately database-agnostic; see
``registry.py`` for how a configured backend is opened.
"""
