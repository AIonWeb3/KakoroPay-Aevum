"""Unit tests for KakoroPay Operator Console."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

from console.src.server import create_app


@pytest.fixture
def mock_w3():
    with patch("console.src.server.Web3") as MockWeb3:
        w3_instance = MagicMock()
        MockWeb3.return_value = w3_instance
        MockWeb3.to_checksum_address.side_effect = lambda a: a
        w3_instance.eth.account.from_key.return_value.address = "0xOwnerAddress"
        w3_instance.eth.get_balance.return_value = 1000000000000000000
        w3_instance.from_wei.return_value = 1.0

        contract = MagicMock()
        w3_instance.eth.contract.return_value = contract
        contract.functions.paused.return_value.call.return_value = False
        contract.functions.owner.return_value.call.return_value = "0xOwnerAddress"
        contract.functions.balanceOf.return_value.call.return_value = 50_000_000

        yield w3_instance


def test_console_status(mock_w3):
    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chainId"] == 44005
    assert data["isPaused"] is False
    assert data["tusd8BalanceFormatted"] == "50.00 tUSD8"
    assert "explorerAccountUrl" in data


def test_record_and_get_events(mock_w3):
    app = create_app()
    client = TestClient(app)

    evt = {
        "type": "PaymentExecuted",
        "txHash": "0x" + "a" * 64,
        "amount": 1000000,
        "sessionKey": "0x" + "b" * 40,
    }
    post_resp = client.post("/api/events/record", json=evt)
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "recorded"

    get_resp = client.get("/api/events")
    assert get_resp.status_code == 200
    events = get_resp.json()
    assert len(events) == 1
    assert events[0]["type"] == "PaymentExecuted"
    assert "explorerUrl" in events[0]
