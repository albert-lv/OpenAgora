"""Smoke tests that openagora_verl no longer monkey patches TransferQueue."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_import_does_not_patch_tq_client():
    """Importing openagora_verl must not modify transfer_queue._TQClient."""
    try:
        import transfer_queue  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("TransferQueue not installed")

    raw_cls = getattr(transfer_queue, "_TQClient", None)
    if raw_cls is None:
        pytest.skip("transfer_queue._TQClient not found")

    # Re-import openagora_verl fresh.
    for mod in list(sys.modules):
        if mod.startswith("openagora_verl"):
            del sys.modules[mod]
    import openagora_verl  # noqa: F401

    after = getattr(raw_cls.async_get_data, "_openagora_patched", False)
    assert after is False, "openagora_verl import must not monkey-patch _TQClient"
