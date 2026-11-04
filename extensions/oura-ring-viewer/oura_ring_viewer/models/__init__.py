"""Custom data models persisted in the Canvas plugin database.

Only the connection is persisted: OAuth tokens and connection status. Oura
data itself is never stored; see ``services/fetch.py``.
"""

from oura_ring_viewer.models.sync_state import OuraSyncState
from oura_ring_viewer.models.tokens import OuraOAuthToken

__all__ = [
    "OuraOAuthToken",
    "OuraSyncState",
]
