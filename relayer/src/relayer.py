"""KakoroPay Relayer FastAPI Service for QDay Aevum Testnet."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from hexbytes import HexBytes
from pydantic import BaseModel, Field
from web3 import Web3

from kakoro_sdk.abi import KAKORO_ACCOUNT_ABI
from kakoro_sdk.constants import AEVUM_RPC_URL, AEVUM_CHAIN_ID, AEVUM_EXPLORER_URL
from kakoro_sdk.types import PaymentIntent


class RelayRequest(BaseModel):
    account: str
    intent: PaymentIntent
    session_sig: str = Field(alias="sessionSig")
    owner_sig: str = Field(default="", alias="ownerSig")


class SimulateRequest(BaseModel):
    account: str
    intent: PaymentIntent
    session_sig: str = Field(alias="sessionSig")
    owner_sig: str = Field(default="", alias="ownerSig")


def create_app(
    rpc_url: str = AEVUM_RPC_URL,
    chain_id: int = AEVUM_CHAIN_ID,
    relayer_private_key: Optional[str] = None,
) -> FastAPI:
    app = FastAPI(title="KakoroPay Relayer", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    private_key = relayer_private_key or os.getenv(
        "RELAYER_PRIVATE_KEY",
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",  # Foundry dev account 0
    )

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    relayer_account = w3.eth.account.from_key(private_key)

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "chainId": chain_id,
            "relayerAddress": relayer_account.address,
        }

    @app.get("/relayer-address")
    async def get_relayer_address() -> Dict[str, str]:
        return {"address": relayer_account.address}

    @app.post("/api/simulate")
    async def simulate_intent(req: SimulateRequest) -> Dict[str, Any]:
        account_addr = Web3.to_checksum_address(req.account)
        contract = w3.eth.contract(address=account_addr, abi=KAKORO_ACCOUNT_ABI)
        
        intent_tuple = (
            Web3.to_checksum_address(req.intent.token),
            Web3.to_checksum_address(req.intent.payee),
            int(req.intent.amount),
            HexBytes(req.intent.ref),
            int(req.intent.deadline),
            int(req.intent.nonce),
        )
        try:
            allowed, reason = contract.functions.simulatePay(
                intent_tuple,
                HexBytes(req.session_sig),
                HexBytes(req.owner_sig) if req.owner_sig else b"",
            ).call()
            return {"allowed": allowed, "reason": reason}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Simulation call error: {str(e)}",
            )

    @app.post("/api/relay")
    async def relay_payment(req: RelayRequest) -> Dict[str, Any]:
        account_addr = Web3.to_checksum_address(req.account)
        contract = w3.eth.contract(address=account_addr, abi=KAKORO_ACCOUNT_ABI)

        intent_tuple = (
            Web3.to_checksum_address(req.intent.token),
            Web3.to_checksum_address(req.intent.payee),
            int(req.intent.amount),
            HexBytes(req.intent.ref),
            int(req.intent.deadline),
            int(req.intent.nonce),
        )

        # 1. Preflight via simulation
        try:
            allowed, reason = contract.functions.simulatePay(
                intent_tuple,
                HexBytes(req.session_sig),
                HexBytes(req.owner_sig) if req.owner_sig else b"",
            ).call()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Simulation error: {str(e)}",
            )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Intent rejected by contract policy: {reason}",
            )

        # 2. Build & submit transaction
        try:
            current_nonce = w3.eth.get_transaction_count(relayer_account.address, "pending")
            gas_price = w3.eth.gas_price

            tx = contract.functions.pay(
                intent_tuple,
                HexBytes(req.session_sig),
                HexBytes(req.owner_sig) if req.owner_sig else b"",
            ).build_transaction({
                "from": relayer_account.address,
                "nonce": current_nonce,
                "gas": 350000,
                "gasPrice": gas_price,
                "chainId": chain_id,
            })

            signed_tx = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash_bytes.hex()

            receipt = w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=45)
            if receipt.get("status") != 1:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"On-chain transaction reverted: {tx_hash_hex}",
                )

            return {
                "status": "success",
                "txHash": tx_hash_hex,
                "blockNumber": receipt.get("blockNumber"),
                "gasUsed": receipt.get("gasUsed"),
                "explorerUrl": f"{AEVUM_EXPLORER_URL}/tx/{tx_hash_hex}",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Relaying transaction failed: {str(e)}",
            )

    return app


app = create_app()
