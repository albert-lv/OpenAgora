"""Tests for ArenaTransferQueueClient adapter."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from openagora_verl.transfer_queue._client import ArenaTransferQueueClient

torch = pytest.importorskip("torch", reason="torch required for adapter tests")


class TestArenaTransferQueueClient:
    def test_delegates_kv_batch_get_and_converts(self):
        from tensordict import TensorDict

        raw = MagicMock()
        prompts = torch.tensor([[0, 1], [0, 2]])
        attention_mask = torch.tensor([[1, 1], [1, 1]])
        raw.kv_batch_get.return_value = TensorDict(
            {"prompts": prompts, "attention_mask": attention_mask},
            batch_size=(2,),
        )

        client = ArenaTransferQueueClient(raw_client=raw)
        result = client.kv_batch_get(
            keys=["k1", "k2"], partition_id="train", select_fields=["prompts"]
        )

        raw.kv_batch_get.assert_called_once_with(
            keys=["k1", "k2"], partition_id="train", select_fields=["prompts"]
        )
        assert result["prompts"].is_nested
        assert not result["attention_mask"].is_nested

    def test_delegates_non_tensor_methods(self):
        raw = MagicMock()
        raw.kv_clear.return_value = None
        client = ArenaTransferQueueClient(raw_client=raw)
        assert client.kv_clear(keys=["k1"], partition_id="train") is None
        raw.kv_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_delegates_async_get_data_and_converts(self):
        from tensordict import TensorDict

        raw = MagicMock()
        raw.async_get_data = AsyncMock(
            return_value=TensorDict(
                {"responses": torch.tensor([[4, 0], [5, 6]])},
                batch_size=(2,),
            )
        )

        client = ArenaTransferQueueClient(raw_client=raw)
        meta = MagicMock()
        result = await client.async_get_data(meta)

        raw.async_get_data.assert_awaited_once_with(meta)
        assert result["responses"].is_nested

    def test_raw_client_property(self):
        raw = MagicMock()
        client = ArenaTransferQueueClient(raw_client=raw)
        assert client.raw_client is raw

    def test_explicit_raw_client_required_when_tq_missing(self):
        # If transfer_queue is missing, constructing without raw_client fails.
        with pytest.raises(RuntimeError):
            ArenaTransferQueueClient()
