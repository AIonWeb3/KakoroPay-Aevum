"""Automated End-to-End Integration Test for KakoroPay."""
import base64
import json
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from eth_account import Account
import pytest

from seller.src.seller import create_app as create_seller_app
from relayer.src.relayer import create_app as create_relayer_app
from kakoro_sdk.signer import sign_payment_intent
from kakoro_sdk.types import PaymentIntent
from kakoro_sdk.verifier import VerificationResult
from kakoro_sdk.constants import AEVUM_CHAIN_ID, DEFAULT_TUSD8_ADDRESS


def test_full_agent_payment_cycle():
    # 1. Accounts
    owner = Account.create()
    session = Account.create()
    seller_acct = Account.create()
    account_contract_address = "0x" + "a" * 40

    mock_verifier = MagicMock()
    seller_app = create_seller_app(
        seller_address=seller_acct.address,
        verifier=mock_verifier,
    )
    seller_client = TestClient(seller_app)

    # 2. Agent requests protected endpoint without payment
    initial_resp = seller_client.get("/api/premium-data")
    assert initial_resp.status_code == 402
    assert "PAYMENT-REQUIRED" in initial_resp.headers

    # 3. Agent parses 402 requirements
    challenge = initial_resp.json()
    invoice_id = challenge["invoiceId"]
    accepts = challenge["accepts"][0]
    required_amount = accepts["amount"]
    token_addr = accepts["asset"]

    # 4. Agent builds and signs EIP-712 PaymentIntent
    intent = PaymentIntent(
        token=token_addr,
        payee=seller_acct.address,
        amount=required_amount,
        ref=invoice_id,
        deadline=1900000000,
        nonce=0,
    )
    session_sig = sign_payment_intent(
        verifying_contract=account_contract_address,
        intent=intent,
        private_key=session.key.hex(),
        chain_id=AEVUM_CHAIN_ID,
    )

    # 5. Relayer relays transaction and generates txHash
    simulated_tx_hash = "0x" + "f" * 64
    mock_verifier.verify_payment.return_value = VerificationResult(
        valid=True,
        reason="Verified on-chain",
        tx_hash=simulated_tx_hash,
        block_number=2800500,
        payer_account=account_contract_address,
        session_key=session.address,
        payee=seller_acct.address,
        token=token_addr,
        amount=required_amount,
        ref=invoice_id,
    )

    # 6. Agent retries request to seller with proof
    proof = {
        "txHash": simulated_tx_hash,
        "invoiceId": invoice_id,
        "account": account_contract_address,
    }
    proof_b64 = base64.b64encode(json.dumps(proof).encode("utf-8")).decode("utf-8")

    retry_resp = seller_client.get(
        "/api/premium-data",
        headers={"PAYMENT-SIGNATURE": proof_b64},
    )

    # 7. Asserts 200 OK and data returned
    assert retry_resp.status_code == 200
    res_data = retry_resp.json()
    assert res_data["status"] == "success"
    assert res_data["service"] == "Alpha Intelligence Feed"
    assert res_data["settlement"]["invoiceId"] == invoice_id
    assert res_data["settlement"]["txHash"] == simulated_tx_hash.lower()

    # 8. Replay is rejected
    replay_resp = seller_client.get(
        "/api/premium-data",
        headers={"PAYMENT-SIGNATURE": proof_b64},
    )
    assert replay_resp.status_code == 409
    assert "Replay detected" in replay_resp.json()["detail"]
