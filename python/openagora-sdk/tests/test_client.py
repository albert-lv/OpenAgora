import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from openagora_sdk.client import ArenaClient


def test_client_init():
    client = ArenaClient("localhost:9090")
    assert client.endpoint == "localhost:9090"
    client.close()
