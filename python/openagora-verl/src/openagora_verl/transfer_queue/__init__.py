"""OpenAgora TransferQueue adapter for veRL.

This package provides clean, non-monkey-patched integration between
TransferQueue and veRL's data-structure expectations.

Public API:

- :class:`ArenaTransferQueueClient` — wraps a raw TransferQueue client and
  converts returned tensors to veRL-compatible nested/padded layout.
- :func:`install_transfer_queue_backend` — registers OpenAgora's arena storage
  backend with TransferQueue's factory when available.
- :func:`convert_tq_tensordict` — converts a TensorDict from padded to
  veRL-compatible hybrid layout.

Example::

    import openagora_verl
    openagora_verl.install_transfer_queue_backend()

    # Or instantiate the client explicitly:
    from openagora_verl.transfer_queue import ArenaTransferQueueClient
    client = ArenaTransferQueueClient(...)
"""

from __future__ import annotations

from openagora_verl.transfer_queue._client import ArenaTransferQueueClient
from openagora_verl.transfer_queue._storage import install_arena_storage_backend
from openagora_verl.transfer_queue._tensor_layout import convert_tq_tensordict


def install_transfer_queue_backend() -> bool:
    """Install OpenAgora's TransferQueue adapter.

    This registers the arena storage backend with TransferQueue if the factory
    API is available. It does not modify any third-party classes at runtime.

    Returns ``True`` if a backend was registered, ``False`` otherwise.
    """
    return install_arena_storage_backend()


__all__ = [
    "ArenaTransferQueueClient",
    "convert_tq_tensordict",
    "install_arena_storage_backend",
    "install_transfer_queue_backend",
]
