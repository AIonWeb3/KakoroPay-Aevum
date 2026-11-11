#!/usr/bin/env python3
"""
Phase 0 — Chain Reconnaissance for QDay Aevum Testnet.

Probes the chain over JSON-RPC and writes findings to docs/CHAIN_FACTS.md.
Run: python scripts/chain_recon.py
"""
from __future__ import annotations

import json
import struct
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ──────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────
RPC_URL = "https://rpc-test.qday.info"
EXPLORER_URL = "https://explorer-test.qday.info"
CHAIN_ID_EXPECTED = 44005
TUSD8_CANDIDATE = "0x456569838f1d43009A91ebA4263147Afd7233483"

# Well-known addresses
ENTRYPOINT_V06 = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
ENTRYPOINT_V07 = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
CREATE2_FACTORY = "0x4e59b44847b379578588920cA78FbF26c0B4956C"  # deterministic deployer
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# ERC-20 function selectors
SEL_NAME = "0x06fdde03"
SEL_SYMBOL = "0x95d89b41"
SEL_DECIMALS = "0x313ce567"
SEL_TOTAL_SUPPLY = "0x18160ddd"
SEL_BALANCE_OF = "0x70a08231"
# EIP-2612 permit
SEL_PERMIT = "0xd505accf"
SEL_NONCES = "0x7ecebe00"
SEL_DOMAIN_SEPARATOR = "0x3644e515"
# EIP-3009 transferWithAuthorization
SEL_TRANSFER_WITH_AUTH = "0xe3ee160e"

_call_id = 0


def _next_id() -> int:
    global _call_id
    _call_id += 1
    return _call_id


# ──────────────────────────────────────────────────────────────────
# JSON-RPC helpers
# ──────────────────────────────────────────────────────────────────
def rpc_call(method: str, params: list | None = None, timeout: int = 15) -> Any:
    """Make a JSON-RPC call, return the 'result' field or raise."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or [],
        "id": _next_id(),
    }
    resp = requests.post(RPC_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"RPC error: {body['error']}")
    return body.get("result")


def eth_call(to: str, data: str, block: str = "latest") -> str | None:
    """eth_call wrapper. Returns hex result or None on revert."""
    try:
        return rpc_call("eth_call", [{"to": to, "data": data}, block])
    except RuntimeError:
        return None


def get_code(address: str) -> str:
    """Return bytecode at address (0x for empty)."""
    return rpc_call("eth_getCode", [address, "latest"]) or "0x"


def has_code(address: str) -> bool:
    code = get_code(address)
    return code is not None and len(code) > 2


def decode_string(hex_data: str) -> str:
    """Decode an ABI-encoded string from hex."""
    if not hex_data or hex_data == "0x":
        return ""
    data = bytes.fromhex(hex_data[2:])
    if len(data) < 64:
        # Non-standard: might be a raw string
        return data.rstrip(b"\x00").decode("utf-8", errors="replace")
    offset = int.from_bytes(data[0:32], "big")
    length = int.from_bytes(data[offset : offset + 32], "big")
    return data[offset + 32 : offset + 32 + length].decode("utf-8", errors="replace")


def decode_uint256(hex_data: str) -> int:
    """Decode a uint256 from hex."""
    if not hex_data or hex_data == "0x":
        return 0
    data = bytes.fromhex(hex_data[2:])
    return int.from_bytes(data[-32:], "big")


def decode_uint8(hex_data: str) -> int:
    """Decode a uint8 from hex."""
    return decode_uint256(hex_data) & 0xFF


def has_function(address: str, selector: str) -> bool:
    """Check if a contract responds to a given function selector (no-arg or zero-padded)."""
    padded = selector + "0" * (64)  # pad with zeros
    result = eth_call(address, padded[:66])  # 4 bytes selector + 32 bytes zero arg
    return result is not None and result != "0x"


# ──────────────────────────────────────────────────────────────────
# Findings collector
# ──────────────────────────────────────────────────────────────────
@dataclass
class Finding:
    category: str
    key: str
    value: Any
    detail: str = ""
    status: str = "INFO"  # OK, WARN, ERROR, INFO


@dataclass
class Findings:
    items: list[Finding] = field(default_factory=list)

    def add(self, category: str, key: str, value: Any, detail: str = "", status: str = "INFO"):
        self.items.append(Finding(category, key, value, detail, status))
        icon = {"OK": "✅", "WARN": "⚠️", "ERROR": "❌", "INFO": "ℹ️"}.get(status, "")
        print(f"  {icon} [{category}] {key} = {value}" + (f"  ({detail})" if detail else ""))


# ──────────────────────────────────────────────────────────────────
# Recon modules
# ──────────────────────────────────────────────────────────────────
def recon_chain_basics(f: Findings):
    print("\n🔗 Chain Basics")
    chain_id_hex = rpc_call("eth_chainId")
    chain_id = int(chain_id_hex, 16) if chain_id_hex else None
    f.add("chain", "chainId", chain_id, f"hex: {chain_id_hex}", "OK" if chain_id == CHAIN_ID_EXPECTED else "ERROR")

    block_num_hex = rpc_call("eth_blockNumber")
    block_num = int(block_num_hex, 16) if block_num_hex else 0
    f.add("chain", "latestBlock", block_num, "", "OK")

    # Get two blocks ~5 apart to estimate block time
    if block_num > 10:
        b1 = rpc_call("eth_getBlockByNumber", [hex(block_num - 5), False])
        b2 = rpc_call("eth_getBlockByNumber", [hex(block_num), False])
        if b1 and b2:
            t1 = int(b1["timestamp"], 16)
            t2 = int(b2["timestamp"], 16)
            avg_block_time = (t2 - t1) / 5
            f.add("chain", "avgBlockTime", f"{avg_block_time:.1f}s", "over last 5 blocks", "OK")

    # Gas price
    gas_price_hex = rpc_call("eth_gasPrice")
    gas_price = int(gas_price_hex, 16) if gas_price_hex else 0
    f.add("chain", "gasPrice", f"{gas_price / 1e9:.4f} gwei", f"raw: {gas_price}", "OK")

    # Network version
    try:
        net_version = rpc_call("net_version")
        f.add("chain", "net_version", net_version, "", "INFO")
    except Exception:
        f.add("chain", "net_version", "unavailable", "", "WARN")

    # Check EIP-1559
    latest_block = rpc_call("eth_getBlockByNumber", ["latest", False])
    has_base_fee = latest_block and "baseFeePerGas" in latest_block
    f.add("chain", "EIP-1559", has_base_fee,
          f"baseFee={int(latest_block['baseFeePerGas'], 16) / 1e9:.4f} gwei" if has_base_fee else "legacy tx only",
          "OK" if has_base_fee else "INFO")


def recon_tusd8(f: Findings):
    print("\n💰 tUSD8 Token Recon")
    addr = TUSD8_CANDIDATE

    # Check code exists
    code_exists = has_code(addr)
    f.add("tUSD8", "hasCode", code_exists, addr, "OK" if code_exists else "ERROR")
    if not code_exists:
        f.add("tUSD8", "RESULT", "NO CONTRACT at candidate address", "Must find or deploy tUSD8", "ERROR")
        return

    # Name
    name_hex = eth_call(addr, SEL_NAME)
    name = decode_string(name_hex) if name_hex else "UNKNOWN"
    f.add("tUSD8", "name", name, "", "OK" if name else "WARN")

    # Symbol
    symbol_hex = eth_call(addr, SEL_SYMBOL)
    symbol = decode_string(symbol_hex) if symbol_hex else "UNKNOWN"
    f.add("tUSD8", "symbol", symbol, "", "OK" if symbol else "WARN")

    # Decimals
    decimals_hex = eth_call(addr, SEL_DECIMALS)
    decimals = decode_uint8(decimals_hex) if decimals_hex else None
    f.add("tUSD8", "decimals", decimals, "expected 6 or 8", "OK" if decimals in (6, 8) else "WARN")

    # Total supply
    supply_hex = eth_call(addr, SEL_TOTAL_SUPPLY)
    supply = decode_uint256(supply_hex) if supply_hex else 0
    supply_human = supply / (10 ** (decimals or 18))
    f.add("tUSD8", "totalSupply", f"{supply_human:,.2f}", f"raw: {supply}", "OK" if supply > 0 else "WARN")

    # EIP-2612 permit support
    has_permit = False
    domain_sep = eth_call(addr, SEL_DOMAIN_SEPARATOR)
    if domain_sep and domain_sep != "0x":
        has_permit = True
        f.add("tUSD8", "EIP-2612_DOMAIN_SEPARATOR", True, domain_sep[:18] + "...", "OK")
    else:
        f.add("tUSD8", "EIP-2612_DOMAIN_SEPARATOR", False, "No permit support", "INFO")

    # Check nonces function (another permit indicator)
    nonces_result = eth_call(addr, SEL_NONCES + "0" * 64)
    if nonces_result and nonces_result != "0x":
        f.add("tUSD8", "EIP-2612_nonces", True, "", "OK")
    else:
        f.add("tUSD8", "EIP-2612_nonces", False, "", "INFO")

    f.add("tUSD8", "EIP-2612_permit", has_permit, "", "OK" if has_permit else "INFO")

    # EIP-3009 transferWithAuthorization
    # Check if the function selector exists in the bytecode
    code = get_code(addr)
    has_3009 = SEL_TRANSFER_WITH_AUTH[2:] in code.lower()
    f.add("tUSD8", "EIP-3009", has_3009, "transferWithAuthorization selector in bytecode" if has_3009 else "Not found", "OK" if has_3009 else "INFO")

    # Check for fee-on-transfer or non-standard return values
    # We can check if transfer returns a bool by examining if there's a return data
    # Standard ERC-20: transfer(address,uint256) -> bool
    # Some tokens don't return anything (USDT-style)
    f.add("tUSD8", "note", "Use SafeERC20 for all transfers to handle non-standard return values", "", "INFO")


def recon_infrastructure(f: Findings):
    print("\n🏗️  Infrastructure Recon")

    # ERC-4337 EntryPoint v0.6
    ep06 = has_code(ENTRYPOINT_V06)
    f.add("infra", "EntryPoint_v0.6", ep06, ENTRYPOINT_V06, "OK" if ep06 else "INFO")

    # ERC-4337 EntryPoint v0.7
    ep07 = has_code(ENTRYPOINT_V07)
    f.add("infra", "EntryPoint_v0.7", ep07, ENTRYPOINT_V07, "OK" if ep07 else "INFO")

    has_entrypoint = ep06 or ep07
    if not has_entrypoint:
        f.add("infra", "ERC-4337", "NOT AVAILABLE",
              "No EntryPoint deployed. Use EIP-712 intents + relayer pattern instead.", "WARN")

    # CREATE2 deterministic deployer
    c2 = has_code(CREATE2_FACTORY)
    f.add("infra", "CREATE2_factory", c2, CREATE2_FACTORY, "OK" if c2 else "INFO")

    # Multicall3
    mc3 = has_code(MULTICALL3)
    f.add("infra", "Multicall3", mc3, MULTICALL3, "OK" if mc3 else "INFO")


def recon_explorer(f: Findings):
    print("\n🔍 Explorer / Verification Recon")
    # Check Blockscout API availability
    try:
        resp = requests.get(f"{EXPLORER_URL}/api/v2/stats", timeout=10)
        if resp.status_code == 200:
            stats = resp.json()
            f.add("explorer", "blockscout_api", True, f"stats endpoint OK", "OK")
            if "total_addresses" in stats:
                f.add("explorer", "total_addresses", stats["total_addresses"], "", "INFO")
            if "total_transactions" in stats:
                f.add("explorer", "total_transactions", stats["total_transactions"], "", "INFO")
        else:
            f.add("explorer", "blockscout_api", False, f"HTTP {resp.status_code}", "WARN")
    except Exception as e:
        f.add("explorer", "blockscout_api", False, str(e), "WARN")

    # Check contract verification API
    try:
        resp = requests.get(f"{EXPLORER_URL}/api/v2/smart-contracts/counters", timeout=10)
        if resp.status_code == 200:
            f.add("explorer", "verification_api", True, "smart-contracts endpoint available", "OK")
        else:
            f.add("explorer", "verification_api", resp.status_code, "", "WARN")
    except Exception as e:
        f.add("explorer", "verification_api", False, str(e), "WARN")

    # Try to get tUSD8 contract info from explorer
    try:
        resp = requests.get(f"{EXPLORER_URL}/api/v2/addresses/{TUSD8_CANDIDATE}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            f.add("explorer", "tUSD8_explorer_name", data.get("name", "N/A"), "", "INFO")
            f.add("explorer", "tUSD8_is_verified", data.get("is_verified", False), "", "INFO")
            f.add("explorer", "tUSD8_is_contract", data.get("is_contract", False), "", "INFO")
            token = data.get("token")
            if token:
                f.add("explorer", "tUSD8_token_type", token.get("type", "N/A"), "", "INFO")
                f.add("explorer", "tUSD8_token_name", token.get("name", "N/A"), "", "INFO")
                f.add("explorer", "tUSD8_token_symbol", token.get("symbol", "N/A"), "", "INFO")
        else:
            f.add("explorer", "tUSD8_explorer", f"HTTP {resp.status_code}", "", "WARN")
    except Exception as e:
        f.add("explorer", "tUSD8_explorer", False, str(e), "WARN")


def recon_rpc_methods(f: Findings):
    print("\n📡 RPC Method Support")
    methods = [
        ("eth_chainId", []),
        ("eth_blockNumber", []),
        ("eth_gasPrice", []),
        ("eth_getBalance", ["0x0000000000000000000000000000000000000000", "latest"]),
        ("eth_getTransactionCount", ["0x0000000000000000000000000000000000000000", "latest"]),
        ("eth_estimateGas", [{"to": "0x0000000000000000000000000000000000000000", "value": "0x0"}]),
        ("eth_getTransactionReceipt", ["0x0000000000000000000000000000000000000000000000000000000000000000"]),
        ("eth_getLogs", [{"fromBlock": "latest", "toBlock": "latest"}]),
        ("eth_getBlockByNumber", ["latest", False]),
        ("debug_traceCall", [{"to": "0x0000000000000000000000000000000000000000"}, "latest", {}]),
        ("eth_maxPriorityFeePerGas", []),
    ]
    for method, params in methods:
        try:
            rpc_call(method, params, timeout=10)
            f.add("rpc", method, "supported", "", "OK")
        except RuntimeError as e:
            err_str = str(e)
            if "not found" in err_str.lower() or "not supported" in err_str.lower() or "does not exist" in err_str.lower():
                f.add("rpc", method, "NOT supported", err_str[:80], "WARN")
            else:
                # Method exists but returned an error for our test params — that's fine
                f.add("rpc", method, "supported (error on test params)", err_str[:80], "OK")
        except Exception as e:
            f.add("rpc", method, "ERROR", str(e)[:80], "WARN")


def recon_faucet(f: Findings):
    print("\n🚰 Faucet Recon")
    try:
        resp = requests.get("https://faucet.qday.info", timeout=10, allow_redirects=True)
        f.add("faucet", "status", resp.status_code, resp.url, "OK" if resp.status_code == 200 else "WARN")
    except Exception as e:
        f.add("faucet", "status", "ERROR", str(e)[:80], "WARN")


# ──────────────────────────────────────────────────────────────────
# Markdown report generator
# ──────────────────────────────────────────────────────────────────
def generate_markdown(f: Findings) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# QDay Aevum Testnet — Chain Facts",
        "",
        f"> Auto-generated by `scripts/chain_recon.py` on {now}.",
        "> Re-run to refresh: `python scripts/chain_recon.py`",
        "",
    ]

    categories = []
    seen = set()
    for item in f.items:
        if item.category not in seen:
            categories.append(item.category)
            seen.add(item.category)

    emoji = {
        "chain": "🔗",
        "tUSD8": "💰",
        "infra": "🏗️",
        "explorer": "🔍",
        "rpc": "📡",
        "faucet": "🚰",
        "design": "📐",
    }

    for cat in categories:
        lines.append(f"## {emoji.get(cat, '📋')} {cat.replace('_', ' ').title()}")
        lines.append("")
        lines.append("| Key | Value | Status | Detail |")
        lines.append("|-----|-------|--------|--------|")
        for item in f.items:
            if item.category == cat:
                status_icon = {"OK": "✅", "WARN": "⚠️", "ERROR": "❌", "INFO": "ℹ️"}.get(item.status, "")
                val = str(item.value).replace("|", "\\|")
                det = str(item.detail).replace("|", "\\|") if item.detail else ""
                lines.append(f"| {item.key} | {val} | {status_icon} {item.status} | {det} |")
        lines.append("")

    # Design decisions section
    lines.append("## 📐 Design Decisions Based on Recon")
    lines.append("")

    # Determine key decisions
    has_ep = any(i.key.startswith("EntryPoint") and i.value is True for i in f.items)
    has_permit = any(i.key == "EIP-2612_permit" and i.value is True for i in f.items)
    has_3009 = any(i.key == "EIP-3009" and i.value is True for i in f.items)
    tusd8_exists = any(i.key == "hasCode" and i.category == "tUSD8" and i.value is True for i in f.items)
    has_1559 = any(i.key == "EIP-1559" and i.value is True for i in f.items)

    decisions = []
    if not has_ep:
        decisions.append(
            "- **Account abstraction**: No ERC-4337 EntryPoint found. "
            "Using **EIP-712 typed-data intents + relayer** pattern instead. "
            "Session keys sign intents off-chain; the relayer submits them with gas."
        )
    else:
        decisions.append("- **Account abstraction**: ERC-4337 EntryPoint available. Could use UserOps but sticking with simpler EIP-712 intents for v1.")

    if not tusd8_exists:
        decisions.append(
            "- **tUSD8**: Candidate address has no code. Need to deploy a test ERC-20 or find the real address."
        )

    if has_permit:
        decisions.append("- **Gasless approvals**: tUSD8 supports EIP-2612 permit. Can use permit for gasless deposit flows.")
    else:
        decisions.append("- **Approvals**: tUSD8 does NOT support EIP-2612 permit. User must send a separate approve() tx.")

    if has_3009:
        decisions.append("- **Gasless transfers**: tUSD8 supports EIP-3009 transferWithAuthorization.")

    if has_1559:
        decisions.append("- **Gas**: EIP-1559 supported. Use type 2 transactions.")
    else:
        decisions.append("- **Gas**: Legacy transactions only. Use type 0 transactions.")

    for d in decisions:
        lines.append(d)
    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  KakoroPay — QDay Aevum Testnet Chain Reconnaissance")
    print("=" * 60)
    print(f"  RPC: {RPC_URL}")
    print(f"  Explorer: {EXPLORER_URL}")
    print(f"  tUSD8 candidate: {TUSD8_CANDIDATE}")
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")

    f = Findings()

    try:
        recon_chain_basics(f)
    except Exception as e:
        f.add("chain", "ERROR", str(e), traceback.format_exc()[:200], "ERROR")

    try:
        recon_tusd8(f)
    except Exception as e:
        f.add("tUSD8", "ERROR", str(e), traceback.format_exc()[:200], "ERROR")

    try:
        recon_infrastructure(f)
    except Exception as e:
        f.add("infra", "ERROR", str(e), traceback.format_exc()[:200], "ERROR")

    try:
        recon_explorer(f)
    except Exception as e:
        f.add("explorer", "ERROR", str(e), traceback.format_exc()[:200], "ERROR")

    try:
        recon_rpc_methods(f)
    except Exception as e:
        f.add("rpc", "ERROR", str(e), traceback.format_exc()[:200], "ERROR")

    try:
        recon_faucet(f)
    except Exception as e:
        f.add("faucet", "ERROR", str(e), traceback.format_exc()[:200], "ERROR")

    # Write markdown
    md = generate_markdown(f)
    out_path = Path(__file__).resolve().parent.parent / "docs" / "CHAIN_FACTS.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"\n📄 Report written to {out_path}")

    # Summary
    errors = [i for i in f.items if i.status == "ERROR"]
    warns = [i for i in f.items if i.status == "WARN"]
    print(f"\n📊 Summary: {len(f.items)} findings, {len(errors)} errors, {len(warns)} warnings")
    if errors:
        print("  ❌ Errors:")
        for e in errors:
            print(f"     - [{e.category}] {e.key}: {e.value}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
