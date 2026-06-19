"""tablint: a pure spreadsheet inspection engine.

Public interface is one function:

    inspect_table(file_path, checks) -> dict

It receives a local file path and returns a structured verdict. It holds no
payment, wallet, x402, Bazaar, or HTTP logic. That all lives in the gateway.
"""

from .engine import ALL_CHECKS, inspect_table

__all__ = ["inspect_table", "ALL_CHECKS"]
__version__ = "0.1.0"
