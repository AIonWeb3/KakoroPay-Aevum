"""CLI utility for KakoroPay Payer."""
from __future__ import annotations

import argparse
import sys
import uvicorn
from web3 import Web3

from .payer import create_app


def main():
    parser = argparse.ArgumentParser(description="KakoroPay Isolated Payer Service")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8002, help="Port to listen on")
    parser.add_argument("--key", help="Session private key (hex)")
    args = parser.parse_args()

    app = create_app(session_private_key=args.key)
    print(f"Starting KakoroPay Payer Signer on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
