"""Unit tests for KakoroPay Seller x402 Service."""
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
import pytest
import json
import base64

from seller.src.seller import create_app
from kakoro_sdk.verifier import VerificationResult


@pytest.fixture
def mock_verifier():
    verifier = MagicMock()
    return verifier


def test_seller_health():
    app = create_app(seller_address="0x" + "1" * 40)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_seller_catalog():
    app = create_app(seller_address="0x" + "1" * 40)
    client = TestClient(app)
    resp = client.get("/catalog")
    assert resp.status_code == 200
    catalog = resp.json()
    assert len(catalog["resources"]) == 2
    assert catalog["resources"][0]["path"] == "/api/premium-data"


def test_seller_402_flow(mock_verifier):
    seller_addr = "0x" + "1" * 40
    app = create_app(seller_address=seller_addr, verifier=mock_verifier)
    client = TestClient(app)

    # 1. Unpaid request gets 402
    resp = client.get("/api/premium-data")
    assert resp.status_code == 402
    assert "PAYMENT-REQUIRED" in resp.headers

    data = resp.json()
    assert data["x402Version"] == 2
    invoice_id = data["invoiceId"]
    assert invoice_id.startswith("0x")
    assert data["accepts"][0]["amount"] == 1_000_000

    # 2. Retry with valid proof
    mock_verifier.verify_payment.return_value = VerificationResult(
        valid=True,
        reason="Verified on-chain",
        tx_hash="0x" + "a" * 64,
        block_number=100,
        payee=seller_addr,
        amount=1_000_000,
        ref=invoice_id,
    )

    proof = {
        "txHash": "0x" + "a" * 64,
        "invoiceId": invoice_id,
    }
    proof_b64 = base64.b64encode(json.dumps(proof).encode("utf-8")).decode("utf-8")

    retry_resp = client.get(
        "/api/premium-data",
        headers={"PAYMENT-SIGNATURE": proof_b64},
    )
    assert retry_resp.status_code == 200
    settled = retry_resp.json()
    assert settled["status"] == "success"
    assert settled["settlement"]["invoiceId"] == invoice_id
    assert settled["data"]["market_trend"] == "BULLISH"

    # 3. Replay attack attempt with same tx_hash fails
    replay_resp = client.get(
        "/api/premium-data",
        headers={"PAYMENT-SIGNATURE": proof_b64},
    )
    assert replay_resp.status_code == 409
    assert "Replay detected" in replay_resp.json()["detail"]


def test_seller_verification_failure(mock_verifier):
    seller_addr = "0x" + "1" * 40
    app = create_app(seller_address=seller_addr, verifier=mock_verifier)
    client = TestClient(app)

    # Trigger 402 to generate invoice
    resp = client.get("/api/premium-data")
    invoice_id = resp.json()["invoiceId"]

    mock_verifier.verify_payment.return_value = VerificationResult(
        valid=False,
        reason="Payment amount below requirement: 500000 < 1000000",
        tx_hash="0x" + "b" * 64,
    )

    proof = {"txHash": "0x" + "b" * 64, "invoiceId": invoice_id}
    retry_resp = client.get(
        "/api/premium-data",
        headers={"X-PAYMENT-PROOF": json.dumps(proof)},
    )
    assert retry_resp.status_code == 402
    assert "Payment verification failed" in retry_resp.json()["detail"]
