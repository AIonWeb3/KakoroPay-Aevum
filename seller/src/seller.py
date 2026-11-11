"""KakoroPay Seller Service implementing x402 on QDay Aevum Testnet."""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from typing import Any, Dict, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from web3 import Web3

from kakoro_sdk.constants import AEVUM_RPC_URL, DEFAULT_TUSD8_ADDRESS
from kakoro_sdk.types import PaymentRequirements, PaymentProof
from kakoro_sdk.verifier import ReceiptVerifier


class Invoice:
    def __init__(self, invoice_id: str, resource: str, amount: int, asset: str, expires_at: float):
        self.invoice_id = invoice_id
        self.resource = resource
        self.amount = amount
        self.asset = asset
        self.expires_at = expires_at
        self.paid = False
        self.tx_hash: Optional[str] = None


def create_app(
    seller_address: Optional[str] = None,
    asset_address: str = DEFAULT_TUSD8_ADDRESS,
    rpc_url: str = AEVUM_RPC_URL,
    verifier: Optional[ReceiptVerifier] = None,
    require_confirmations: int = 1,
) -> FastAPI:
    app = FastAPI(title="KakoroPay 402 Merchant Service", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    pay_to = Web3.to_checksum_address(seller_address or os.getenv(
        "SELLER_ADDRESS",
        "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",  # Default test seller (Foundry account 1)
    ))
    token_addr = Web3.to_checksum_address(asset_address)
    receipt_verifier = verifier or ReceiptVerifier(rpc_url=rpc_url)

    # In-memory invoice and replay prevention store
    invoices: Dict[str, Invoice] = {}
    used_tx_hashes: set[str] = set()

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "sellerAddress": pay_to,
            "asset": token_addr,
            "chain": "eip155:44005",
        }

    @app.get("/catalog")
    async def get_catalog() -> Dict[str, Any]:
        return {
            "seller": pay_to,
            "network": "eip155:44005",
            "asset": token_addr,
            "resources": [
                {
                    "path": "/api/premium-data",
                    "name": "Alpha Intelligence Feed",
                    "price_raw": 1_000_000,
                    "price_human": "1.00 tUSD8",
                    "method": "GET",
                },
                {
                    "path": "/api/inference",
                    "name": "Llama-3-70B Agent Inference",
                    "price_raw": 2_000_000,
                    "price_human": "2.00 tUSD8",
                    "method": "POST",
                },
            ],
        }

    def _extract_payment_proof(
        payment_signature: Optional[str],
        x_payment_proof: Optional[str],
    ) -> Optional[PaymentProof]:
        raw_dict = None
        if payment_signature:
            try:
                decoded = base64.b64decode(payment_signature).decode("utf-8")
                raw_dict = json.loads(decoded)
            except Exception:
                pass
        elif x_payment_proof:
            try:
                raw_dict = json.loads(x_payment_proof)
            except Exception:
                pass

        if raw_dict:
            try:
                return PaymentProof(**raw_dict)
            except Exception:
                return None
        return None

    def _create_402_response(resource: str, cost: int) -> JSONResponse:
        invoice_id = "0x" + secrets.token_hex(32)
        invoices[invoice_id] = Invoice(
            invoice_id=invoice_id,
            resource=resource,
            amount=cost,
            asset=token_addr,
            expires_at=time.time() + 300,
        )

        req_body = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:44005",
                    "asset": token_addr,
                    "payTo": pay_to,
                    "amount": cost,
                    "invoiceId": invoice_id,
                    "maxTimeoutSeconds": 300,
                }
            ],
            "invoiceId": invoice_id,
        }

        req_bytes = json.dumps(req_body).encode("utf-8")
        req_b64 = base64.b64encode(req_bytes).decode("utf-8")

        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content=req_body,
            headers={"PAYMENT-REQUIRED": req_b64},
        )

    @app.get("/api/premium-data")
    async def get_premium_data(
        payment_signature: Optional[str] = Header(None, alias="PAYMENT-SIGNATURE"),
        x_payment_proof: Optional[str] = Header(None, alias="X-PAYMENT-PROOF"),
    ) -> Response:
        cost = 1_000_000  # 1.00 tUSD8 (6 decimals)
        proof = _extract_payment_proof(payment_signature, x_payment_proof)

        if not proof:
            return _create_402_response("/api/premium-data", cost)

        # Replay prevention on tx_hash
        norm_tx_hash = proof.tx_hash.lower()
        if norm_tx_hash in used_tx_hashes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Replay detected: tx {norm_tx_hash} has already been settled",
            )

        invoice = invoices.get(proof.invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown or expired invoiceId: {proof.invoice_id}",
            )

        if time.time() > invoice.expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invoice has expired",
            )

        # On-chain verification
        result = receipt_verifier.verify_payment(
            tx_hash=proof.tx_hash,
            expected_payee=pay_to,
            expected_token=token_addr,
            min_amount=invoice.amount,
            expected_ref=invoice.invoice_id,
            min_confirmations=require_confirmations,
        )

        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Payment verification failed: {result.reason}",
            )

        # Mark paid
        invoice.paid = True
        invoice.tx_hash = norm_tx_hash
        used_tx_hashes.add(norm_tx_hash)

        return JSONResponse({
            "status": "success",
            "service": "Alpha Intelligence Feed",
            "data": {
                "market_trend": "BULLISH",
                "volatility_index": 18.4,
                "recommended_position": "LONG_AERO",
                "confidence": 0.94,
                "timestamp": int(time.time()),
            },
            "settlement": {
                "invoiceId": invoice.invoice_id,
                "amount": invoice.amount,
                "token": invoice.asset,
                "payee": pay_to,
                "txHash": norm_tx_hash,
                "blockNumber": result.block_number,
            },
        })

    @app.post("/api/inference")
    async def post_inference(
        req: Request,
        payment_signature: Optional[str] = Header(None, alias="PAYMENT-SIGNATURE"),
        x_payment_proof: Optional[str] = Header(None, alias="X-PAYMENT-PROOF"),
    ) -> Response:
        cost = 2_000_000  # 2.00 tUSD8 (6 decimals)
        proof = _extract_payment_proof(payment_signature, x_payment_proof)

        if not proof:
            return _create_402_response("/api/inference", cost)

        norm_tx_hash = proof.tx_hash.lower()
        if norm_tx_hash in used_tx_hashes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Replay detected: tx {norm_tx_hash} has already been settled",
            )

        invoice = invoices.get(proof.invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown or expired invoiceId: {proof.invoice_id}",
            )

        result = receipt_verifier.verify_payment(
            tx_hash=proof.tx_hash,
            expected_payee=pay_to,
            expected_token=token_addr,
            min_amount=invoice.amount,
            expected_ref=invoice.invoice_id,
            min_confirmations=require_confirmations,
        )

        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Payment verification failed: {result.reason}",
            )

        invoice.paid = True
        invoice.tx_hash = norm_tx_hash
        used_tx_hashes.add(norm_tx_hash)

        body = await req.json() if req.headers.get("content-type") == "application/json" else {}
        prompt = body.get("prompt", "Hello")

        return JSONResponse({
            "status": "success",
            "service": "Llama-3-70B Agent Inference",
            "output": f"AI Response to '{prompt}': Successfully computed on-chain verified workflow.",
            "settlement": {
                "invoiceId": invoice.invoice_id,
                "amount": invoice.amount,
                "token": invoice.asset,
                "payee": pay_to,
                "txHash": norm_tx_hash,
                "blockNumber": result.block_number,
            },
        })

    return app


app = create_app()
