"""OpenAgora TransferQueue client adapter for veRL.

This module provides :class:`ArenaTransferQueueClient`, a clean wrapper around
TransferQueue's low-level ``_TQClient``. It applies the nested/padded tensor
conversion defined in ``_tensor_layout.py`` to data returned by TransferQueue,
so that veRL receives the hybrid layout it expects.

No monkey patching is performed: callers instantiate this client explicitly or
use :func:`openagora_verl.install_transfer_queue_backend` to register the
OpenAgora storage backend with TransferQueue.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openagora_verl.transfer_queue._tensor_layout import maybe_convert_value

logger = logging.getLogger(__name__)


def _get_raw_tq_client_class() -> Optional[type]:
    """Return TransferQueue's private ``_TQClient`` class if available."""
    try:
        import transfer_queue  # type: ignore[import-not-found]

        return getattr(transfer_queue, "_TQClient", None)
    except Exception:
        return None


class ArenaTransferQueueClient:
    """veRL-compatible wrapper around a TransferQueue ``_TQClient`` instance.

    The wrapper forwards all attribute access to the underlying raw client and
    post-processes any returned ``TensorDict`` so that ``prompts``/``responses``
    become nested tensors while ``attention_mask`` stays padded.

    Args:
        raw_client: An initialized TransferQueue ``_TQClient`` instance. If
            ``None``, a new raw client is created from TransferQueue's default
            constructor using ``*args``/``**kwargs``.
        *args: Positional arguments passed to the raw client constructor when
            ``raw_client`` is ``None``.
        **kwargs: Keyword arguments passed to the raw client constructor when
            ``raw_client`` is ``None``.
    """

    def __init__(self, raw_client: Optional[Any] = None, *args: Any, **kwargs: Any):
        if raw_client is not None:
            self._raw = raw_client
            return

        raw_cls = _get_raw_tq_client_class()
        if raw_cls is None:
            raise RuntimeError(
                "TransferQueue is not installed; cannot create ArenaTransferQueueClient"
            )
        self._raw = raw_cls(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Forward attribute access to the raw client.

        Methods that return TensorDict are wrapped so the result is converted
        to veRL-compatible layout.
        """
        attr = getattr(self._raw, name)

        if not callable(attr):
            return attr

        # Wrap async and sync methods that are known to return TensorDict data.
        import inspect

        if inspect.iscoroutinefunction(attr):

            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = await attr(*args, **kwargs)
                return maybe_convert_value(result)

            return _async_wrapper

        # Synchronous wrapper.
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = attr(*args, **kwargs)
            return maybe_convert_value(result)

        return _sync_wrapper

    def kv_batch_get(
        self,
        keys: list[str],
        partition_id: str,
        select_fields: Optional[list[str]] = None,
    ) -> Any:
        """Fetch samples from TransferQueue and convert tensor layout."""
        result = self._raw.kv_batch_get(
            keys=keys, partition_id=partition_id, select_fields=select_fields
        )
        return maybe_convert_value(result)

    async def async_kv_batch_get(
        self,
        keys: list[str],
        partition_id: str,
        select_fields: Optional[list[str]] = None,
    ) -> Any:
        """Async fetch samples from TransferQueue and convert tensor layout."""
        raw_method = self._raw.async_kv_batch_get
        result = await raw_method(
            keys=keys, partition_id=partition_id, select_fields=select_fields
        )
        return maybe_convert_value(result)

    async def async_get_data(self, meta: Any) -> Any:
        """Mirror ``_TQClient.async_get_data`` with veRL layout conversion."""
        raw_method = self._raw.async_get_data
        result = await raw_method(meta)
        return maybe_convert_value(result)

    @property
    def raw_client(self) -> Any:
        """Expose the wrapped TransferQueue client for advanced use cases."""
        return self._raw
