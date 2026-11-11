"""KakoroPay Model Context Protocol (MCP) Server for Autonomous Agents."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
import httpx
from web3 import Web3

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from kakoro_sdk.abi import KAKORO_ACCOUNT_ABI
from kakoro_sdk.client import KakoroClient
from kakoro_sdk.constants import AEVUM_RPC_URL, AEVUM_CHAIN_ID
from kakoro_sdk.ssrf import validate_url


def create_mcp_server(name: str = "kakoropay-agent-wallet") -> MCPServer:
    mcp = MCPServer(name)

    @mcp.tool()
    async def discover_resources(catalog_url: str, allow_loopback: bool = False) -> Dict[str, Any]:
        """
        Discovers paid APIs and merchant resource endpoints from a catalog with SSRF protection.
        """
        validate_url(catalog_url, allow_http=True, allow_loopback=allow_loopback)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(catalog_url)
            if resp.status_code != 200:
                return {
                    "status": "error",
                    "error": f"Failed to fetch catalog: status {resp.status_code}",
                }
            return {
                "status": "ok",
                "catalog": resp.json() if "application/json" in resp.headers.get("content-type", "") else resp.text,
            }

    @mcp.tool()
    def check_budget(
        account_address: str,
        session_key: str,
        rpc_url: str = AEVUM_RPC_URL,
    ) -> Dict[str, Any]:
        """
        Queries the on-chain KakoroAccount smart account for remaining session budget and rate limits.
        """
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            account_chk = Web3.to_checksum_address(account_address)
            session_chk = Web3.to_checksum_address(session_key)

            contract = w3.eth.contract(address=account_chk, abi=KAKORO_ACCOUNT_ABI)
            is_active = contract.functions.isSessionActive(session_chk).call()

            if not is_active:
                return {
                    "is_active": False,
                    "remaining_spend": 0,
                    "remaining_calls": 0,
                    "window_reset_time": 0,
                    "message": "Session is inactive or expired.",
                }

            spend, calls, reset_time = contract.functions.getBudgetRemaining(session_chk).call()
            return {
                "is_active": True,
                "remaining_spend_raw": spend,
                "remaining_spend_tusd8": f"{spend / 1_000_000:.2f} tUSD8",
                "remaining_calls": calls,
                "window_reset_time": reset_time,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to query on-chain budget: {str(e)}",
            }

    @mcp.tool()
    async def pay_and_call(
        account_address: str,
        session_private_key: str,
        resource_url: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        relayer_url: Optional[str] = None,
        rpc_url: str = AEVUM_RPC_URL,
        allow_loopback: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes a policy-bounded paid API call: handles HTTP 402, signs EIP-712 session intent,
        relays to KakoroAccount, and retries with cryptographic settlement proof.
        """
        try:
            client = KakoroClient(
                account_address=account_address,
                session_private_key=session_private_key,
                relayer_url=relayer_url,
                rpc_url=rpc_url,
                allow_loopback=allow_loopback,
            )

            status_code, response_data = await client.pay_and_call(
                url=resource_url,
                method=method,
                data=data,
            )

            return {
                "status_code": status_code,
                "response": response_data,
                "success": (200 <= status_code < 300),
            }
        except Exception as e:
            return {
                "status_code": 500,
                "error": f"pay_and_call execution failed: {str(e)}",
                "success": False,
            }

    return mcp


mcp_server = create_mcp_server()


if __name__ == "__main__":
    mcp_server.run()
