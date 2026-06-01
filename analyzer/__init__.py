"""
Analyzer module — read-only statistical reports on archived content.

No network requests.  No filesystem writes.  SQLite reads only.
"""
from .reporter import generate_report

__all__ = ["generate_report"]
