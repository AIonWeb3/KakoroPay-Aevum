#!/usr/bin/env python3
"""
Python Deployment Script for KakoroPay Contracts on QDay Aevum Testnet (ChainId 44005).

Deploys:
  1. PayeeRegistry(owner)
  2. KakoroAccount(owner, payeeRegistry)

Outputs:
  - deployments/44005.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# Defaults
DEFAULT_RPC_URL = "https://rpc-test.qday.info"
DEFAULT_CHAIN_ID = 44005
DEFAULT_EXPLORER_URL = "https://explorer-test.qday.info"
DEFAULT_TUSD8 = "0x456569838f1d43009A91ebA4263147Afd7233483"

ROOT_DIR = Path(__file__).resolve().parent.parent
CONTRACTS_OUT = ROOT_DIR / "contracts" / "out"
DEPLOYMENTS_DIR = ROOT_DIR / "deployments"


def load_env() -> Dict[str, str]:
    """Simple parser for .env file if python-dotenv is not active."""
    env: Dict[str, str] = {}
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    return env


def load_artifact(contract_name: str) -> Dict[str, Any]:
    """Loads compiled Foundry JSON artifact."""
    artifact_path = CONTRACTS_OUT / f"{contract_name}.sol" / f"{contract_name}.json"
    if not artifact_path.exists():
        raise FileNotFoundError(
            f"Artifact not found at {artifact_path}. "
            "Please ensure contracts have been built via 'forge build'."
        )
    with open(artifact_path, "r", encoding="utf-8") as f:
        return json.load(f)


def deploy_contract(
    w3: Web3,
    account: Any,
    contract_name: str,
    constructor_args: list,
    gas_limit: int = 4_000_000,
) -> tuple[str, str, int]:
    """Deploys a contract using EIP-1559 or legacy tx on Aevum."""
    print(f"\n📦 Preparing deployment for {contract_name}...")
    artifact = load_artifact(contract_name)
    abi = artifact["abi"]
    bytecode = artifact["bytecode"]["object"]
    if not bytecode or bytecode == "0x":
        raise ValueError(f"No bytecode found in artifact for {contract_name}")

    ContractFactory = w3.eth.contract(abi=abi, bytecode=bytecode)
    construct_txn = ContractFactory.constructor(*constructor_args)

    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas_price = w3.eth.gas_price

    tx = construct_txn.build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": int(gas_price * 1.2),  # 20% margin
        "chainId": DEFAULT_CHAIN_ID,
    })

    signed_tx = account.sign_transaction(tx)
    print(f"🚀 Broadcasting {contract_name} deployment (nonce: {nonce})...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    hex_hash = tx_hash.hex()
    print(f"   Tx Hash: {hex_hash}")
    print(f"   Explorer: {DEFAULT_EXPLORER_URL}/tx/{hex_hash}")

    print("⏳ Waiting for transaction receipt...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120, poll_latency=1.0)
    if receipt.status != 1:
        raise RuntimeError(f"Deployment failed for {contract_name}! Status: {receipt.status}")

    contract_address = receipt.contractAddress
    print(f"✅ {contract_name} deployed at: {contract_address} (block {receipt.blockNumber})")
    return contract_address, hex_hash, receipt.blockNumber


def main():
    print("=" * 65)
    print("  KakoroPay: QDay Aevum Testnet Deployment")
    print("=" * 65)

    env = load_env()
    rpc_url = os.environ.get("AEVUM_RPC_URL") or env.get("AEVUM_RPC_URL") or DEFAULT_RPC_URL
    private_key = os.environ.get("PRIVATE_KEY") or env.get("PRIVATE_KEY")

    if not private_key:
        print("\n❌ Error: PRIVATE_KEY is not set.")
        print("Please configure PRIVATE_KEY in your environment or in a .env file.")
        print("To get testnet tQDAY for gas, visit: https://faucet.qday.info/en")
        sys.exit(1)

    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    deployer = Account.from_key(private_key)
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        print(f"❌ Cannot connect to RPC at {rpc_url}")
        sys.exit(1)

    chain_id = w3.eth.chain_id
    balance_wei = w3.eth.get_balance(deployer.address)
    balance_tqday = w3.from_wei(balance_wei, "ether")

    print(f"Connected to Chain ID: {chain_id}")
    print(f"Deployer Address:      {deployer.address}")
    print(f"Deployer Balance:      {balance_tqday:.4f} tQDAY")

    if balance_wei < w3.to_wei(0.005, "ether"):
        print("\n⚠️ Insufficient tQDAY balance for deployment (need at least 0.005 tQDAY).")
        print("Request faucet funds at: https://faucet.qday.info/en")
        sys.exit(1)

    DEPLOYMENTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Deploy PayeeRegistry
    registry_addr, registry_tx, registry_block = deploy_contract(
        w3, deployer, "PayeeRegistry", [deployer.address]
    )

    # 2. Deploy KakoroAccount
    account_addr, account_tx, account_block = deploy_contract(
        w3, deployer, "KakoroAccount", [deployer.address, registry_addr]
    )

    # 3. Save to deployments/44005.json
    deployment_record = {
        "chainId": chain_id,
        "chainName": "QDay Aevum Testnet",
        "rpcUrl": rpc_url,
        "explorerUrl": DEFAULT_EXPLORER_URL,
        "deployedAt": datetime.now(timezone.utc).isoformat(),
        "deployer": deployer.address,
        "contracts": {
            "PayeeRegistry": {
                "address": registry_addr,
                "txHash": registry_tx,
                "blockNumber": registry_block,
                "explorerUrl": f"{DEFAULT_EXPLORER_URL}/address/{registry_addr}",
            },
            "KakoroAccount": {
                "address": account_addr,
                "txHash": account_tx,
                "blockNumber": account_block,
                "explorerUrl": f"{DEFAULT_EXPLORER_URL}/address/{account_addr}",
            },
            "tUSD8": {
                "address": DEFAULT_TUSD8,
                "decimals": 6,
                "symbol": "tUSD8",
                "explorerUrl": f"{DEFAULT_EXPLORER_URL}/address/{DEFAULT_TUSD8}",
            },
        },
    }

    deployment_file = DEPLOYMENTS_DIR / "44005.json"
    with open(deployment_file, "w", encoding="utf-8") as f:
        json.dump(deployment_record, f, indent=2)

    print("\n" + "=" * 65)
    print(f"🎉 Deployment saved to {deployment_file}")
    print(f"   PayeeRegistry: {registry_addr}")
    print(f"   KakoroAccount: {account_addr}")
    print("=" * 65)


if __name__ == "__main__":
    main()
