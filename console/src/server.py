"""KakoroPay Operator Console FastAPI Server."""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from web3 import Web3

from kakoro_sdk.abi import KAKORO_ACCOUNT_ABI, ERC20_ABI
from kakoro_sdk.constants import AEVUM_RPC_URL, AEVUM_CHAIN_ID, AEVUM_EXPLORER_URL, DEFAULT_TUSD8_ADDRESS


STATIC_DIR = Path(__file__).resolve().parent / "static"


class RevokeRequest(BaseModel):
    session_key: str


class GrantSessionRequest(BaseModel):
    session_key: str
    expiry: int
    per_call_cap: int
    window_cap: int
    window_seconds: int = 3600
    max_calls: int = 20
    approval_threshold: int = 5_000_000
    require_verified_payee: bool = False
    allowed_payees: List[str] = []


def create_app(
    account_address: Optional[str] = None,
    owner_private_key: Optional[str] = None,
    rpc_url: str = AEVUM_RPC_URL,
    chain_id: int = AEVUM_CHAIN_ID,
    token_address: str = DEFAULT_TUSD8_ADDRESS,
) -> FastAPI:
    app = FastAPI(title="KakoroPay Operator Console", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    account_addr = Web3.to_checksum_address(
        account_address or os.getenv("KAKORO_ACCOUNT_ADDRESS", "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    )
    owner_key = owner_private_key or os.getenv(
        "OWNER_PRIVATE_KEY",
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    )
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    owner_acct = w3.eth.account.from_key(owner_key)
    account_contract = w3.eth.contract(address=account_addr, abi=KAKORO_ACCOUNT_ABI)
    token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)

    # In-memory cached audit event log for fast console viewing
    event_history: List[Dict[str, Any]] = []

    @app.get("/api/status")
    async def get_status() -> Dict[str, Any]:
        try:
            # Query contract state
            paused = account_contract.functions.paused().call()
            owner = account_contract.functions.owner().call()
        except Exception:
            paused = False
            owner = owner_acct.address

        try:
            token_balance = token_contract.functions.balanceOf(account_addr).call()
        except Exception:
            token_balance = 0

        try:
            native_balance = w3.eth.get_balance(account_addr)
        except Exception:
            native_balance = 0

        return {
            "accountAddress": account_addr,
            "ownerAddress": owner,
            "chainId": chain_id,
            "network": "QDay Aevum Testnet",
            "isPaused": paused,
            "tusd8BalanceRaw": token_balance,
            "tusd8BalanceFormatted": f"{token_balance / 1_000_000:.2f} tUSD8",
            "nativeBalance": f"{w3.from_wei(native_balance, 'ether'):.4f} QDAY",
            "explorerAccountUrl": f"{AEVUM_EXPLORER_URL}/address/{account_addr}",
        }

    @app.get("/api/events")
    async def get_events() -> List[Dict[str, Any]]:
        return list(reversed(event_history))

    @app.post("/api/events/record")
    async def record_event(evt: Dict[str, Any]) -> Dict[str, str]:
        evt["timestamp"] = int(time.time())
        if "txHash" in evt and "explorerUrl" not in evt:
            evt["explorerUrl"] = f"{AEVUM_EXPLORER_URL}/tx/{evt['txHash']}"
        event_history.append(evt)
        return {"status": "recorded"}

    @app.post("/api/pause")
    async def pause_account() -> Dict[str, Any]:
        try:
            nonce = w3.eth.get_transaction_count(owner_acct.address, "pending")
            tx = account_contract.functions.pause().build_transaction({
                "from": owner_acct.address,
                "nonce": nonce,
                "gas": 100000,
                "gasPrice": w3.eth.gas_price,
                "chainId": chain_id,
            })
            signed = w3.eth.account.sign_transaction(tx, owner_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            evt = {
                "type": "AccountPaused",
                "account": account_addr,
                "txHash": tx_hash,
                "blockNumber": receipt.get("blockNumber"),
                "timestamp": int(time.time()),
                "explorerUrl": f"{AEVUM_EXPLORER_URL}/tx/{tx_hash}",
            }
            event_history.append(evt)

            return {"status": "paused", "txHash": tx_hash}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Pause failed: {str(e)}")

    @app.post("/api/unpause")
    async def unpause_account() -> Dict[str, Any]:
        try:
            nonce = w3.eth.get_transaction_count(owner_acct.address, "pending")
            tx = account_contract.functions.unpause().build_transaction({
                "from": owner_acct.address,
                "nonce": nonce,
                "gas": 100000,
                "gasPrice": w3.eth.gas_price,
                "chainId": chain_id,
            })
            signed = w3.eth.account.sign_transaction(tx, owner_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            evt = {
                "type": "AccountUnpaused",
                "account": account_addr,
                "txHash": tx_hash,
                "blockNumber": receipt.get("blockNumber"),
                "timestamp": int(time.time()),
                "explorerUrl": f"{AEVUM_EXPLORER_URL}/tx/{tx_hash}",
            }
            event_history.append(evt)

            return {"status": "unpaused", "txHash": tx_hash}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unpause failed: {str(e)}")

    @app.post("/api/revoke")
    async def revoke_session(req: RevokeRequest) -> Dict[str, Any]:
        try:
            target_key = Web3.to_checksum_address(req.session_key)
            nonce = w3.eth.get_transaction_count(owner_acct.address, "pending")
            tx = account_contract.functions.revokeSession(target_key).build_transaction({
                "from": owner_acct.address,
                "nonce": nonce,
                "gas": 100000,
                "gasPrice": w3.eth.gas_price,
                "chainId": chain_id,
            })
            signed = w3.eth.account.sign_transaction(tx, owner_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            evt = {
                "type": "SessionRevoked",
                "sessionKey": target_key,
                "txHash": tx_hash,
                "blockNumber": receipt.get("blockNumber"),
                "timestamp": int(time.time()),
                "explorerUrl": f"{AEVUM_EXPLORER_URL}/tx/{tx_hash}",
            }
            event_history.append(evt)

            return {"status": "revoked", "sessionKey": target_key, "txHash": tx_hash}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Revoke failed: {str(e)}")

    @app.get("/api/stream")
    async def event_stream() -> StreamingResponse:
        async def generator() -> AsyncGenerator[str, None]:
            last_count = 0
            while True:
                if len(event_history) > last_count:
                    new_events = event_history[last_count:]
                    last_count = len(event_history)
                    for e in new_events:
                        yield f"data: {json.dumps(e)}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(generator(), media_type="text/event-stream")

    # Serve static assets
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def root():
            index_file = STATIC_DIR / "index.html"
            if index_file.exists():
                return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>KakoroPay Operator Console</h1>")

    return app


app = create_app()
