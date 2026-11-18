"""API tests watch blocks one at a time (save_block, delete_block, build_delete_block_effects).

The block route saves and deletes in batches (save_blocks, delete_blocks,
build_delete_blocks_effects), which the engine tests cover directly. Here the
batch helpers hand each block to the single-block ones, looked up when called,
so a test that patches a single-block helper sees every block.
"""

from unittest.mock import patch

import pytest

API = "provider_availability.api.availability_api"


@pytest.fixture(autouse=True)
def _batched_blocks_one_at_a_time():
    import provider_availability.api.availability_api as api

    def save_blocks(blocks):
        for b in blocks:
            api.save_block(b)

    def delete_blocks(blocks):
        for b in blocks:
            api.delete_block(b.provider_id, b.id)

    def delete_effects(blocks, skip_ids=None, lookups=None):
        skip = set(skip_ids or set()) | {b.id for b in blocks}
        out = []
        for b in blocks:
            out.extend(api.build_delete_block_effects(b.provider_id, b, skip_ids=skip))
        return out

    with patch(f"{API}.save_blocks", side_effect=save_blocks), \
         patch(f"{API}.delete_blocks", side_effect=delete_blocks), \
         patch(f"{API}.build_delete_blocks_effects", side_effect=delete_effects):
        yield
