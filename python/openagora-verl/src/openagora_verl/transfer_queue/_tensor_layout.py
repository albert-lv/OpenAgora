"""Tensor layout conversion utilities for TransferQueue → veRL compatibility.

TransferQueue's default storage backends return all tensor fields as padded
2-D tensors. veRL's data pipeline (especially ``use_remove_padding=True``)
expects a hybrid layout:

- ``prompts`` and ``responses`` must be ``torch.nested`` tensors (jagged layout).
- ``attention_mask`` must remain a padded 2-D tensor.
- Other variable-length fields become nested tensors; fixed-length fields stay
  padded.

This module provides the conversion functions without any monkey patching.
It is used by :class:`openagora_verl.transfer_queue.ArenaTransferQueueClient`
and by the OpenAgora TransferQueue storage backend.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch
    from tensordict import TensorDict

logger = logging.getLogger(__name__)

FORCE_NESTED_FIELDS = frozenset({"prompts", "responses"})
FORCE_PADDED_FIELDS = frozenset({"attention_mask"})


def tensor_to_nested(values: list["torch.Tensor"]) -> "torch.Tensor":  # type: ignore[name-defined]
    """Convert a list of 1-D tensors into a jagged nested tensor."""
    import torch

    flattened = [v.flatten() if v.dim() > 0 else v.unsqueeze(0) for v in values]
    return torch.nested.as_nested_tensor(flattened, layout=torch.jagged)


def tensor_to_padded(values: list["torch.Tensor"]) -> "torch.Tensor":  # type: ignore[name-defined]
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


def convert_tq_tensordict(td: "TensorDict") -> "TensorDict":  # type: ignore[name-defined]
    """Convert a TensorDict returned by TransferQueue into veRL-compatible layout.

    The input ``td`` is expected to contain per-field tensors in padded 2-D
    layout (the default TransferQueue representation). The output TensorDict
    has ``prompts``/``responses`` converted to nested tensors and
    ``attention_mask`` left padded, matching veRL's ``no_padding_2_padding``
    contract.

    Non-tensor fields and scalar fields are preserved unchanged.
    """
    import torch
    from tensordict import TensorDict as TD

    if td is None or (hasattr(td, "batch_size") and td.batch_size[0] == 0):
        return td

    result: dict[str, Any] = {}
    for field, value in td.items():
        if isinstance(value, torch.Tensor):
            # If the field is already nested, leave it alone.
            if value.is_nested:
                result[field] = value
                continue

            # Split the 2-D padded tensor into a list of 1-D tensors, one per
            # sample, by using the field-specific layout rule.
            if field in FORCE_PADDED_FIELDS:
                result[field] = value
                continue

            # Determine whether this field is variable-length.
            samples = [value[i] for i in range(value.shape[0])]
            lengths = [s.numel() for s in samples]
            use_nested = field in FORCE_NESTED_FIELDS or len(set(lengths)) > 1

            if use_nested:
                try:
                    result[field] = tensor_to_nested(samples)
                except Exception as exc:  # pragma: no cover - defensive fallback
                    logger.warning(
                        "[TQ adapter] Failed to build nested tensor for %s: %s; "
                        "falling back to padded",
                        field,
                        exc,
                    )
                    result[field] = value
            else:
                result[field] = value
        elif isinstance(value, (int, float)):
            result[field] = value
        else:
            result[field] = value

    # Preserve batch size and any non-tensor data that TensorDict tracks.
    return TD(result, batch_size=td.batch_size)


def maybe_convert_value(value: Any) -> Any:
    """Convert a single value returned by TransferQueue if it is a TensorDict."""
    # Avoid importing tensordict at module load; this module is imported early.
    try:
        from tensordict import TensorDict as TD
    except Exception:
        return value

    if isinstance(value, TD):
        return convert_tq_tensordict(value)
    return value
