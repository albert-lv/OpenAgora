"""OpenAgora TransferQueue storage backend adapter for veRL.

This module optionally registers an "arena" storage backend with
TransferQueue's pluggable storage factory. The backend wraps TransferQueue's
default ``SimpleStorage`` but applies the nested/padded tensor conversion on
``get_data`` so that veRL receives the data layout it expects.

If TransferQueue is not installed, or its storage factory API is unavailable,
this module becomes a no-op and :class:`ArenaTransferQueueClient` should be
used directly instead.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openagora_verl.transfer_queue._tensor_layout import convert_tq_tensordict

logger = logging.getLogger(__name__)

# Type aliases for optional TransferQueue base classes.
_StorageManagerType: Optional[type] = None
_KVStorageManagerType: Optional[type] = None
_StorageClientType: Optional[type] = None


def _resolve_tq_classes() -> tuple[Optional[type], Optional[type], Optional[type]]:
    """Import TransferQueue storage base classes if available."""
    try:
        import transfer_queue  # type: ignore[import-not-found]

        manager_cls = getattr(transfer_queue, "StorageManager", None)
        kv_manager_cls = getattr(transfer_queue, "KVStorageManager", None)
        client_cls = getattr(transfer_queue, "StorageClient", None)

        # Some versions expose these under storage submodules.
        if manager_cls is None:
            try:
                from transfer_queue.storage.managers.base import StorageManager  # type: ignore[import-not-found]

                manager_cls = StorageManager
            except Exception:
                pass
        if kv_manager_cls is None:
            try:
                from transfer_queue.storage.managers.base import KVStorageManager  # type: ignore[import-not-found]

                kv_manager_cls = KVStorageManager
            except Exception:
                pass
        if client_cls is None:
            try:
                from transfer_queue.storage.clients.base import StorageClient  # type: ignore[import-not-found]

                client_cls = StorageClient
            except Exception:
                pass

        return manager_cls, kv_manager_cls, client_cls
    except Exception:
        return None, None, None


_StorageManagerType, _KVStorageManagerType, _StorageClientType = _resolve_tq_classes()


class ArenaStorageClient:
    """Storage client adapter that converts retrieved data to veRL layout.

    This wraps a raw TransferQueue storage client (e.g. ``SimpleStorageClient``)
    and applies :func:`convert_tq_tensordict` to values returned by
    ``get_data``/``kv_batch_get``.
    """

    def __init__(self, raw_client: Any) -> None:
        self._raw = raw_client

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._raw, name)
        if not callable(attr):
            return attr

        import inspect

        if inspect.iscoroutinefunction(attr):

            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = await attr(*args, **kwargs)
                return (
                    convert_tq_tensordict(result)
                    if name in ("get_data", "kv_batch_get")
                    else result
                )

            return _async_wrapper

        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = attr(*args, **kwargs)
            return (
                convert_tq_tensordict(result)
                if name in ("get_data", "kv_batch_get")
                else result
            )

        return _sync_wrapper


class ArenaStorageManager:
    """Storage manager adapter that returns an ``ArenaStorageClient``.

    This wraps a raw TransferQueue ``StorageManager`` (or ``KVStorageManager``)
    and intercepts client creation so that all read operations go through
    :class:`ArenaStorageClient`.
    """

    def __init__(self, raw_manager: Any) -> None:
        self._raw = raw_manager

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._raw, name)
        if not callable(attr):
            return attr

        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            result = attr(*args, **kwargs)
            # If the raw manager returns a storage client, wrap it.
            if (
                name in ("get_client", "create_client", "kv_client")
                and result is not None
            ):
                return ArenaStorageClient(result)
            return result

        return _wrapper


def _build_arena_storage_backend(raw_backend_cls: type) -> type:
    """Dynamically create an arena-flavored storage backend class."""

    class ArenaStorageBackend(raw_backend_cls):  # type: ignore[valid-type,misc]
        """Arena adapter around a concrete TransferQueue storage backend."""

        async def get_data(self, data: Any, metadata: Any) -> Any:
            result = await super().get_data(data, metadata)  # type: ignore[misc]
            return convert_tq_tensordict(result)

    return ArenaStorageBackend


def install_arena_storage_backend() -> bool:
    """Register OpenAgora's arena backend with TransferQueue if possible.

    Returns ``True`` if registration succeeded, ``False`` otherwise. This
    function never raises; it logs an informative message when TransferQueue is
    unavailable or does not expose a factory API.
    """
    try:
        import transfer_queue  # type: ignore[import-not-found]
    except Exception:
        logger.debug(
            "TransferQueue not installed; skipping arena storage backend registration"
        )
        return False

    # Attempt 1: factory-based registration.
    factory = getattr(transfer_queue, "StorageManagerFactory", None)
    if factory is None:
        try:
            from transfer_queue.storage.managers.base import StorageManagerFactory  # type: ignore[import-not-found]

            factory = StorageManagerFactory
        except Exception:
            pass

    if factory is not None and hasattr(factory, "register"):
        try:
            from transfer_queue.storage.managers.simple_storage_manager import (  # type: ignore[import-not-found]
                AsyncSimpleStorageManager,
            )

            arena_cls = _build_arena_storage_backend(AsyncSimpleStorageManager)
            factory.register("arena", arena_cls)
            logger.info(
                "Registered OpenAgora arena storage backend with TransferQueue factory"
            )
            return True
        except Exception as exc:
            logger.warning(
                "TransferQueue factory found but arena backend registration failed: %s",
                exc,
            )

    # Attempt 2: if a global default storage manager exists, wrap it.
    default_manager = getattr(transfer_queue, "_default_storage_manager", None)
    if default_manager is not None:
        try:
            transfer_queue._default_storage_manager = ArenaStorageManager(
                default_manager
            )  # type: ignore[attr-defined]
            logger.info(
                "Wrapped TransferQueue default storage manager with ArenaStorageManager"
            )
            return True
        except Exception as exc:
            logger.warning(
                "Failed to wrap TransferQueue default storage manager: %s", exc
            )

    logger.debug(
        "No usable TransferQueue storage backend registration point found; "
        "use ArenaTransferQueueClient explicitly"
    )
    return False
