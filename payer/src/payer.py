"""KakoroPay Payer Service — Isolated Session Signer."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from web3 import Web3

from kakoro_sdk.constants import AEVUM_CHAIN_ID
from kakoro_sdk.signer import sign_payment_intent
from kakoro_sdk.types import PaymentIntent


class LocalPolicyConfig(BaseModel):
    max_amount_per_call: int = 10_000_000  # 10 tUSD8 default guardrail
    allowed_payees: Optional[List[str]] = None


class SignIntentRequest(BaseModel):
    account: str
    intent: PaymentIntent


def create_app(
    session_private_key: Optional[str] = None,
    chain_id: int = AEVUM_CHAIN_ID,
    policy: Optional[LocalPolicyConfig] = None,
) -> FastAPI:
    app = FastAPI(title="KakoroPay Payer Isolated Signer", version="1.0.0")

    private_key = session_private_key or os.getenv(
        "SESSION_PRIVATE_KEY",
        "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",  # Foundry dev account 1
    )
    w3 = Web3()
    session_account = w3.eth.account.from_key(private_key)
    local_policy = policy or LocalPolicyConfig()

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "sessionKey": session_account.address,
            "maxLocalAmount": local_policy.max_amount_per_call,
        }

    @app.get("/session-key")
    async def get_session_key() -> Dict[str, str]:
        return {"sessionKey": session_account.address}

    @app.post("/sign-intent")
    async def sign_intent(req: SignIntentRequest) -> Dict[str, str]:
        # 1. Enforce local signer guardrails
        if req.intent.amount > local_policy.max_amount_per_call:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Amount {req.intent.amount} exceeds local safety cap {local_policy.max_amount_per_call}",
            )

        if local_policy.allowed_payees is not None:
            norm_payees = [Web3.to_checksum_address(p) for p in local_policy.allowed_payees]
            norm_target = Web3.to_checksum_address(req.intent.payee)
            if norm_target not in norm_payees:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Payee {req.intent.payee} not in local allowlist",
                )

        # 2. Cryptographic EIP-712 signature
        account_addr = Web3.to_checksum_address(req.account)
        sig = sign_payment_intent(
            verifying_contract=account_addr,
            intent=req.intent,
            private_key=private_key,
            chain_id=chain_id,
        )

        return {
            "sessionSig": sig,
            "sessionKey": session_account.address,
        }

    return app


app = create_app()
