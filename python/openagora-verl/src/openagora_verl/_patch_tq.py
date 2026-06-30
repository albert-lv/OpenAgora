"""OpenAgora-side compatibility layer for the TransferQueue package.

veRL 0.9.0.dev uses TransferQueue to move ``DataProto``/``TensorDict`` objects
between workers. TransferQueue's default ``async_get_data`` returns all tensor
fields as padded 2-D tensors, but veRL's ``no_padding_2_padding`` utility
expects:

- ``prompts`` and ``responses`` to be ``torch.nested`` tensors (jagged layout)
- ``attention_mask`` to be a padded 2-D tensor

This module provides a runtime compatibility adapter that converts the tensors
returned by TransferQueue into the shape contract veRL expects. It is purely an
OpenAgora adapter: no changes are made to veRL or TransferQueue source code.

The patch is applied automatically when ``openagora_verl`` is imported unless
``OPENAGORA_DISABLE_TQ_PATCH=1`` is set in the environment.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch
    from tensordict import TensorDict

logger = logging.getLogger(__name__)

_FORCE_NESTED_FIELDS = frozenset({"prompts", "responses"})
_FORCE_PADDED_FIELDS = frozenset({"attention_mask"})


def _tensor_to_nested(values: list[torch.Tensor]) -> torch.Tensor:  # type: ignore[name-defined]
    """Convert a list of 1-D tensors into a jagged nested tensor."""
    import torch

    flattened = [v.flatten() if v.dim() > 0 else v.unsqueeze(0) for v in values]
    return torch.nested.as_nested_tensor(flattened, layout=torch.jagged)


def _tensor_to_padded(values: list[torch.Tensor]) -> torch.Tensor:  # type: ignore[name-defined]
    """Convert a list of 1-D tensors into a padded 2-D tensor."""
    import torch

    lengths = [v.numel() for v in values]
    max_len = max(lengths) if lengths else 0
    if max_len == 0:
        raise ValueError("Cannot build padded tensor from empty values")
    padded = torch.zeros(
        len(values), max_len, dtype=values[0].dtype, device=values[0].device
    )
    for i, v in enumerate(values):
        if v.numel():
            padded[i, : v.numel()] = v.flatten()
    return padded


async def _arena_async_get_data(self, meta) -> "TensorDict":  # type: ignore[name-defined]
    """Fetch stored fields and convert them to veRL-compatible nested/padded tensors.

    This implementation mirrors the contract of TransferQueue's
    ``AsyncTransferQueueClient.async_get_data`` but post-processes the fields
    so that ``prompts``/``responses`` are nested and ``attention_mask`` is
    padded. All other tensor fields are auto-detected: variable-length tensors
    become nested, fixed-length tensors stay padded.
    """
    import torch
    from tensordict import TensorDict as TD
    from tensordict.tensorclass import NonTensorData

    keys = meta.keys
    partition_id = meta.partition_id
    select_fields = meta.field_names

    raw = await self._handle.kv_batch_get.remote(  # type: ignore[attr-defined]
        keys=keys, partition_id=partition_id, select_fields=select_fields
    )

    if not raw:
        return TD({}, batch_size=(0,))

    if select_fields:
        all_fields = select_fields
    else:
        all_fields = set()
        for entry in raw:
            if entry:
                all_fields.update(entry.keys())
        all_fields = list(all_fields)

    result: dict[str, Any] = {}
    for field in all_fields:
        values = [entry.get(field) if entry else None for entry in raw]
        non_none = [v for v in values if v is not None]
        if not non_none:
            continue

        first = non_none[0]
        if isinstance(first, torch.Tensor):
            lengths = [v.numel() for v in non_none]
            if field in _FORCE_PADDED_FIELDS:
                use_nested = False
            elif field in _FORCE_NESTED_FIELDS:
                use_nested = True
            else:
                use_nested = len(set(lengths)) > 1

            if use_nested:
                try:
                    tensors = [
                        v.flatten() if v.dim() > 0 else v.unsqueeze(0) for v in non_none
                    ]
                    if len(non_none) < len(values):
                        filled = []
                        nn_iter = iter(tensors)
                        for v in values:
                            if v is not None:
                                filled.append(next(nn_iter))
                            else:
                                filled.append(
                                    torch.zeros(
                                        0, dtype=first.dtype, device=first.device
                                    )
                                )
                        tensors = filled
                    result[field] = torch.nested.as_nested_tensor(
                        tensors, layout=torch.jagged
                    )
                except Exception as exc:  # pragma: no cover - defensive fallback
                    logger.warning(
                        "[TQ] Failed to build nested tensor for %s: %s; falling back to padded",
                        field,
                        exc,
                    )
                    result[field] = _tensor_to_padded(non_none)
            else:
                result[field] = _tensor_to_padded(non_none)
        elif isinstance(first, (int, float)):
            result[field] = torch.tensor(
                [v if v is not None else 0 for v in values],
                dtype=torch.int64 if isinstance(first, int) else torch.float32,
            )
        else:
            result[field] = NonTensorData(data=values, batch_size=[len(values)])

    return TD(result, batch_size=[len(keys)])


def _apply_transfer_queue_patch() -> bool:
    """Apply the OpenAgora TransferQueue compatibility adapter if available."""
    if os.environ.get("OPENAGORA_DISABLE_TQ_PATCH", "0") == "1":
        logger.debug(
            "OPENAGORA_DISABLE_TQ_PATCH=1; skipping TransferQueue compatibility patch"
        )
        return False

    try:
        import transfer_queue  # type: ignore[import-not-found]
    except ImportError:
        logger.debug(
            "TransferQueue not installed; skipping OpenAgora compatibility patch"
        )
        return False

    try:
        tq_client = transfer_queue._TQClient
    except AttributeError:
        logger.warning(
            "TransferQueue installed but _TQClient not found; skipping compatibility patch"
        )
        return False

    # Avoid double-patching if openagora_verl is imported multiple times.
    if getattr(tq_client.async_get_data, "_openagora_patched", False):
        return True

    tq_client._FORCE_NESTED_FIELDS = _FORCE_NESTED_FIELDS
    tq_client._FORCE_PADDED_FIELDS = _FORCE_PADDED_FIELDS
    tq_client.async_get_data = _arena_async_get_data  # type: ignore[method-assign]
    tq_client.async_get_data._openagora_patched = True  # type: ignore[attr-defined]
    logger.info("Applied OpenAgora TransferQueue compatibility patch for veRL")
    return True
