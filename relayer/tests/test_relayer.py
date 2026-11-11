"""Unit tests for KakoroPay Relayer service."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest
from hexbytes import HexBytes

from relayer.src.relayer import create_app
from kakoro_sdk.types import PaymentIntent


@pytest.fixture
def mock_w3():
    with patch("relayer.src.relayer.Web3") as MockWeb3:
        w3_instance = MagicMock()
        MockWeb3.return_value = w3_instance
        MockWeb3.to_checksum_address.side_effect = lambda addr: addr
        w3_instance.eth.account.from_key.return_value.address = "0xRelayerAddress"
        w3_instance.eth.get_transaction_count.return_value = 1
        w3_instance.eth.gas_price = 1000000000
        w3_instance.eth.send_raw_transaction.return_value = HexBytes("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        w3_instance.eth.wait_for_transaction_receipt.return_value = {
            "status": 1,
            "blockNumber": 42,
            "gasUsed": 150000,
        }
        yield w3_instance


def test_health(mock_w3):
    app = create_app(relayer_private_key="0x" + "1" * 64)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["chainId"] == 44005
    assert data["relayerAddress"] == "0xRelayerAddress"


def test_relayer_address(mock_w3):
    app = create_app(relayer_private_key="0x" + "1" * 64)
    client = TestClient(app)
    resp = client.get("/relayer-address")
    assert resp.status_code == 200
    assert resp.json()["address"] == "0xRelayerAddress"


def test_simulate_allowed(mock_w3):
    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract
    mock_contract.functions.simulatePay.return_value.call.return_value = (True, "")

    app = create_app(relayer_private_key="0x" + "1" * 64)
    client = TestClient(app)

    payload = {
        "account": "0x2222222222222222222222222222222222222222",
        "intent": {
            "token": "0x456569838f1d43009A91ebA4263147Afd7233483",
            "payee": "0x1111111111111111111111111111111111111111",
            "amount": 1000000,
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
        "sessionSig": "0x" + "3" * 130,
        "ownerSig": "",
    }
    resp = client.post("/api/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed"] is True
    assert data["reason"] == ""


def test_simulate_disallowed(mock_w3):
    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract
    mock_contract.functions.simulatePay.return_value.call.return_value = (False, "OverPerCallCap")

    app = create_app(relayer_private_key="0x" + "1" * 64)
    client = TestClient(app)

    payload = {
        "account": "0x2222222222222222222222222222222222222222",
        "intent": {
            "token": "0x456569838f1d43009A91ebA4263147Afd7233483",
            "payee": "0x1111111111111111111111111111111111111111",
            "amount": 10000000,
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
        "sessionSig": "0x" + "3" * 130,
        "ownerSig": "",
    }
    resp = client.post("/api/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed"] is False
    assert data["reason"] == "OverPerCallCap"


def test_relay_rejected_by_policy(mock_w3):
    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract
    mock_contract.functions.simulatePay.return_value.call.return_value = (False, "PayeeNotAllowed")

    app = create_app(relayer_private_key="0x" + "1" * 64)
    client = TestClient(app)

    payload = {
        "account": "0x2222222222222222222222222222222222222222",
        "intent": {
            "token": "0x456569838f1d43009A91ebA4263147Afd7233483",
            "payee": "0x1111111111111111111111111111111111111111",
            "amount": 1000000,
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
        "sessionSig": "0x" + "3" * 130,
        "ownerSig": "",
    }
    resp = client.post("/api/relay", json=payload)
    assert resp.status_code == 400
    assert "Intent rejected by contract policy" in resp.json()["detail"]


def test_relay_success(mock_w3):
    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract
    mock_contract.functions.simulatePay.return_value.call.return_value = (True, "")
    mock_contract.functions.pay.return_value.build_transaction.return_value = {
        "from": "0xRelayerAddress",
        "nonce": 1,
        "gas": 350000,
        "gasPrice": 1000000000,
        "chainId": 44005,
    }

    app = create_app(relayer_private_key="0x" + "1" * 64)
    client = TestClient(app)

    payload = {
        "account": "0x2222222222222222222222222222222222222222",
        "intent": {
            "token": "0x456569838f1d43009A91ebA4263147Afd7233483",
            "payee": "0x1111111111111111111111111111111111111111",
            "amount": 1000000,
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
        "sessionSig": "0x" + "3" * 130,
        "ownerSig": "",
    }
    resp = client.post("/api/relay", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "txHash" in data
    assert data["blockNumber"] == 42
    assert "explorerUrl" in data
