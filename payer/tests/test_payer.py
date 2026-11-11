"""Unit tests for KakoroPay Payer Isolated Signer."""
from fastapi.testclient import TestClient
import pytest
from eth_account import Account
from web3 import Web3

from payer.src.payer import create_app, LocalPolicyConfig
from kakoro_sdk.constants import AEVUM_CHAIN_ID


def test_payer_health_and_session_key():
    key = "0x" + "2" * 64
    expected_address = Account.from_key(key).address

    app = create_app(session_private_key=key)
    client = TestClient(app)

    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["sessionKey"] == expected_address

    key_resp = client.get("/session-key")
    assert key_resp.status_code == 200
    assert key_resp.json()["sessionKey"] == expected_address


def test_payer_signs_intent():
    key = "0x" + "2" * 64
    account_addr = "0x" + "3" * 40
    payee_addr = "0x" + "4" * 40
    token_addr = "0x" + "5" * 40

    app = create_app(session_private_key=key)
    client = TestClient(app)

    payload = {
        "account": account_addr,
        "intent": {
            "token": token_addr,
            "payee": payee_addr,
            "amount": 1000000,
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
    }

    resp = client.post("/sign-intent", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "sessionSig" in data
    assert data["sessionSig"].startswith("0x")
    assert len(data["sessionSig"]) == 132  # 65 bytes in hex + 0x


def test_payer_blocks_over_local_cap():
    key = "0x" + "2" * 64
    policy = LocalPolicyConfig(max_amount_per_call=500_000)

    app = create_app(session_private_key=key, policy=policy)
    client = TestClient(app)

    payload = {
        "account": "0x" + "3" * 40,
        "intent": {
            "token": "0x" + "5" * 40,
            "payee": "0x" + "4" * 40,
            "amount": 1_000_000,  # Exceeds 500_000
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
    }

    resp = client.post("/sign-intent", json=payload)
    assert resp.status_code == 400
    assert "exceeds local safety cap" in resp.json()["detail"]


def test_payer_blocks_unauthorized_payee():
    key = "0x" + "2" * 64
    allowed = ["0x" + "4" * 40]
    policy = LocalPolicyConfig(allowed_payees=allowed)

    app = create_app(session_private_key=key, policy=policy)
    client = TestClient(app)

    payload = {
        "account": "0x" + "3" * 40,
        "intent": {
            "token": "0x" + "5" * 40,
            "payee": "0x" + "9" * 40,  # Not in allowed
            "amount": 1000,
            "ref": "0x" + "a" * 64,
            "deadline": 1800000000,
            "nonce": 0,
        },
    }

    resp = client.post("/sign-intent", json=payload)
    assert resp.status_code == 400
    assert "not in local allowlist" in resp.json()["detail"]
