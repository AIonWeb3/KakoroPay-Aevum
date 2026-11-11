"""KakoroPay Agent Client for x402 resource payments."""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, Optional, Tuple
import httpx
from web3 import Web3
from hexbytes import HexBytes

from .abi import KAKORO_ACCOUNT_ABI
from .constants import AEVUM_RPC_URL, AEVUM_CHAIN_ID
from .signer import sign_payment_intent
from .ssrf import validate_url
from .types import PaymentIntent, PaymentRequirements, PaymentProof, SessionBudget


class KakoroPaymentError(Exception):
    """Raised when an on-chain or policy payment failure occurs."""
    def __init__(self, message: str, code: str = "PAYMENT_FAILED", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class KakoroClient:
    """Agent payment client for executing policy-bounded payments."""

    def __init__(
        self,
        account_address: str,
        session_private_key: str,
        relayer_url: Optional[str] = None,
        rpc_url: str = AEVUM_RPC_URL,
        chain_id: int = AEVUM_CHAIN_ID,
        allow_loopback: bool = False,
    ):
        self.account_address = Web3.to_checksum_address(account_address)
        self.session_key = Web3().eth.account.from_key(session_private_key).address
        self.session_private_key = session_private_key
        self.relayer_url = relayer_url
        self.chain_id = chain_id
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.contract = self.w3.eth.contract(address=self.account_address, abi=KAKORO_ACCOUNT_ABI)
        self.allow_loopback = allow_loopback

    def get_budget(self) -> SessionBudget:
        """Retrieves active session remaining spend and calls."""
        is_active = self.contract.functions.isSessionActive(self.session_key).call()
        if not is_active:
            return SessionBudget(
                remaining_spend=0,
                remaining_calls=0,
                window_reset_time=0,
                is_active=False,
            )
        remaining_spend, remaining_calls, window_reset = self.contract.functions.getBudgetRemaining(self.session_key).call()
        return SessionBudget(
            remaining_spend=remaining_spend,
            remaining_calls=remaining_calls,
            window_reset_time=window_reset,
            is_active=True,
        )

    def get_nonce(self) -> int:
        """Retrieves current session nonce from contract."""
        return self.contract.functions.sessionNonces(self.session_key).call()

    def simulate_pay(
        self,
        intent: PaymentIntent,
        session_sig: str,
        owner_sig: str = "",
    ) -> Tuple[bool, str]:
        """Preflights a payment using contract simulation."""
        intent_tuple = (
            Web3.to_checksum_address(intent.token),
            Web3.to_checksum_address(intent.payee),
            int(intent.amount),
            HexBytes(intent.ref),
            int(intent.deadline),
            int(intent.nonce),
        )
        return self.contract.functions.simulatePay(
            intent_tuple,
            HexBytes(session_sig),
            HexBytes(owner_sig) if owner_sig else b"",
        ).call()

    def create_intent(
        self,
        reqs: PaymentRequirements,
        deadline_seconds: int = 300,
    ) -> PaymentIntent:
        """Generates a PaymentIntent based on seller payment requirements."""
        nonce = self.get_nonce()
        deadline = int(time.time()) + deadline_seconds

        ref_str = reqs.invoice_id
        if not ref_str.startswith("0x"):
            ref_str = Web3.keccak(text=ref_str).hex()

        return PaymentIntent(
            token=reqs.asset,
            payee=reqs.pay_to,
            amount=reqs.amount,
            ref=ref_str,
            deadline=deadline,
            nonce=nonce,
        )

    def sign_intent(self, intent: PaymentIntent) -> str:
        """Signs the intent using session private key."""
        return sign_payment_intent(
            verifying_contract=self.account_address,
            intent=intent,
            private_key=self.session_private_key,
            chain_id=self.chain_id,
        )

    async def execute_payment(
        self,
        intent: PaymentIntent,
        session_sig: str,
        owner_sig: str = "",
        relayer_private_key: Optional[str] = None,
    ) -> str:
        """Submits the signed payment intent on-chain (via relayer URL or direct key)."""
        # 1. Preflight via simulation
        allowed, reason = self.simulate_pay(intent, session_sig, owner_sig)
        if not allowed:
            raise KakoroPaymentError(f"Preflight simulation rejected: {reason}", code=reason)

        # 2. Relayer submission
        if self.relayer_url:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.relayer_url}/api/relay",
                    json={
                        "account": self.account_address,
                        "intent": intent.model_dump(),
                        "sessionSig": session_sig,
                        "ownerSig": owner_sig,
                    },
                )
                if resp.status_code != 200:
                    raise KakoroPaymentError(f"Relayer failed: {resp.text}", code="RELAYER_ERROR")
                data = resp.json()
                return data["txHash"]

        # Fallback: Submit directly if a relayer private key is provided locally
        if relayer_private_key:
            relayer_acct = self.w3.eth.account.from_key(relayer_private_key)
            intent_tuple = (
                Web3.to_checksum_address(intent.token),
                Web3.to_checksum_address(intent.payee),
                int(intent.amount),
                HexBytes(intent.ref),
                int(intent.deadline),
                int(intent.nonce),
            )
            tx = self.contract.functions.pay(
                intent_tuple,
                HexBytes(session_sig),
                HexBytes(owner_sig) if owner_sig else b"",
            ).build_transaction({
                "from": relayer_acct.address,
                "nonce": self.w3.eth.get_transaction_count(relayer_acct.address),
                "gas": 300000,
                "gasPrice": self.w3.eth.gas_price,
            })
            signed_tx = self.w3.eth.account.sign_transaction(tx, relayer_private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            # Wait for receipt
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status != 1:
                raise KakoroPaymentError("Transaction reverted on-chain", code="TX_REVERTED")
            return tx_hash.hex()

        raise KakoroPaymentError("No relayer endpoint or relayer key configured", code="NO_RELAYER")

    async def pay_and_call(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        relayer_private_key: Optional[str] = None,
    ) -> Tuple[int, Any]:
        """
        Executes HTTP request, intercepts 402, evaluates policy, pays, and returns final response.
        """
        # SSRF Protection
        validate_url(url, allow_http=True, allow_loopback=self.allow_loopback)

        req_headers = headers.copy() if headers else {}
        async with httpx.AsyncClient(timeout=15.0) as http:
            # 1. Initial attempt
            resp = await http.request(method, url, headers=req_headers, json=data)
            if resp.status_code != 402:
                return resp.status_code, resp.json() if "application/json" in resp.headers.get("content-type", "") else resp.text

            # 2. Extract payment requirements from 402
            req_header = resp.headers.get("PAYMENT-REQUIRED")
            if req_header:
                req_json = json.loads(base64.b64decode(req_header).decode("utf-8"))
            else:
                req_json = resp.json()

            # Parse payment requirements
            accepts = req_json.get("accepts", [req_json])[0]
            requirements = PaymentRequirements(
                x402Version=req_json.get("x402Version", 2),
                scheme=accepts.get("scheme", "exact"),
                network=accepts.get("network", "eip155:44005"),
                asset=accepts.get("asset"),
                payTo=accepts.get("payTo"),
                amount=int(accepts.get("amount")),
                invoiceId=accepts.get("invoiceId") or req_json.get("invoiceId"),
                maxTimeoutSeconds=accepts.get("maxTimeoutSeconds", 300),
            )

            # 3. Create & sign intent
            intent = self.create_intent(requirements)
            session_sig = self.sign_intent(intent)

            # 4. Broadcast payment
            tx_hash = await self.execute_payment(
                intent,
                session_sig,
                relayer_private_key=relayer_private_key,
            )

            # 5. Retry request with proof
            proof = PaymentProof(txHash=tx_hash, invoiceId=requirements.invoice_id, account=self.account_address)
            proof_b64 = base64.b64encode(json.dumps(proof.model_dump(by_alias=True)).encode("utf-8")).decode("utf-8")

            req_headers["PAYMENT-SIGNATURE"] = proof_b64
            req_headers["X-PAYMENT-PROOF"] = json.dumps(proof.model_dump(by_alias=True))

            retry_resp = await http.request(method, url, headers=req_headers, json=data)
            return retry_resp.status_code, retry_resp.json() if "application/json" in retry_resp.headers.get("content-type", "") else retry_resp.text
