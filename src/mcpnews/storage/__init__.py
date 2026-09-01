"""Blob storage for the article archive: local by default, remote later.

The interface is in ``base.py``; ``backends/remote.py`` records what each remote
backend would need, including the OAuth flow, so the interface can be judged
against them rather than only against a local folder.
"""
