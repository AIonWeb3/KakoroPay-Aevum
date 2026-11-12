"""
KakoroPay Agent Starter Template (QDay Aevum Testnet).

Demonstrates how an autonomous AI agent makes policy-bounded micropayments
to HTTP 402 merchant endpoints using gasless session keys.
"""
import asyncio
import os
import sys
from eth_account import Account
from kakoro_sdk.client import KakoroClient
from kakoro_sdk.constants import AEVUM_CHAIN_ID, DEFAULT_TUSD8_ADDRESS

# Configuration
AEVUM_RPC_URL = os.environ.get("AEVUM_RPC_URL", "https://rpc-test.qday.info")
RELAYER_URL = os.environ.get("RELAYER_URL", "http://127.0.0.1:8002")
VAULT_CONTRACT = os.environ.get("KAKORO_ACCOUNT_ADDRESS", "0x" + "a" * 40)
MERCHANT_URL = os.environ.get("MERCHANT_URL", "http://127.0.0.1:8001/api/premium-data")


async def main():
    print("=== KakoroPay Autonomous Agent Client ===")

    # 1. Ephemeral Session Key (Holds 0 native gas and 0 tokens)
    session = Account.create()
    print(f"Agent Session Address: {session.address}")

    # 2. Initialize KakoroClient
    client = KakoroClient(
        account_address=VAULT_CONTRACT,
        session_private_key=session.key.hex(),
        relayer_url=RELAYER_URL,
        rpc_url=AEVUM_RPC_URL,
        chain_id=AEVUM_CHAIN_ID,
        allow_loopback=True,  # Set False in production to enforce strict SSRF protection
    )

    print(f"Requesting protected resource from: {MERCHANT_URL}...")
    try:
        # 3. pay_and_fetch handles:
        #    - Unpaid request -> receives HTTP 402 Payment Required
        #    - Parses invoice & payment requirements
        #    - Validates against local budget & payee allowlist
        #    - Signs EIP-712 PaymentIntent
        #    - Relays intent via gasless relayer
        #    - Retries request with PAYMENT-SIGNATURE proof
        #    - Returns paid response
        resp = await client.pay_and_fetch(MERCHANT_URL, method="GET")
        print("\n✅ Resource acquired successfully!")
        print("Status code:", resp.status_code)
        print("Payload:", resp.json())
    except Exception as e:
        print(f"❌ Payment flow failed: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
