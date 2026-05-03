"""Share a created segment with one or more Adobe Analytics users."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def share_segment(client: object, segment_id: str, user_ids: list[str]) -> None:
    """Share *segment_id* with each user in *user_ids* via *client*."""
    if not user_ids:
        return
    logger.debug("Sharing segment %s with %d user(s)", segment_id, len(user_ids))
    await client.share_segment(segment_id, user_ids)  # type: ignore[attr-defined]
    logger.debug("Shared segment %s", segment_id)
