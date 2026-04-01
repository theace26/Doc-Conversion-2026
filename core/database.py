"""
Backward-compatible re-export wrapper.

All database functionality has been split into domain modules under ``core.db``.
This file re-exports every public symbol so that existing ``from core.database
import ...`` statements continue to work unchanged.
"""

# Re-export everything from the domain-split package
from core.db import *  # noqa: F401,F403
from core.db import __all__  # noqa: F401
