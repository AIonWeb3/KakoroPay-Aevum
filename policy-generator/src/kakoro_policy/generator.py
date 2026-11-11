"""Data-Derived Policy Generator for EVM Smart Accounts."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from web3 import Web3

from .schema import SessionPolicySpec
from kakoro_sdk.constants import DEFAULT_TUSD8_ADDRESS


class PolicyInputError(Exception):
    """Raised when input transaction log is malformed or empty."""
    pass


REQUIRED_TX_FIELDS = {"payee", "amount", "timestamp"}


def percentile(data: List[float], p: float) -> float:
    """Calculates percentile using standard nearest rank method."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def parse_timestamp(ts: Any) -> float:
    """Parses ISO timestamp string or numeric unix epoch."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return float(ts)
        except ValueError:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
    raise PolicyInputError(f"Cannot parse timestamp: {ts}")


def score_transactions(
    tx_log: List[Dict[str, Any]],
    session_key: str = "0x0000000000000000000000000000000000000000",
    default_token: str = DEFAULT_TUSD8_ADDRESS,
    safety_margin: float = 1.25,
    approval_multiplier: float = 1.5,
    fixed_window_seconds: int = 3600,
    session_duration_seconds: int = 86400 * 7,  # 7 days
    require_verified_payee: bool = False,
) -> SessionPolicySpec:
    """
    Computes a data-derived spend policy from historical agent payment transactions.
    """
    if not tx_log:
        raise PolicyInputError("Transaction log is empty")

    amounts: List[float] = []
    payees: set[str] = set()
    tokens: set[str] = set()
    timestamps: List[float] = []

    for idx, tx in enumerate(tx_log):
        for field in REQUIRED_TX_FIELDS:
            if field not in tx:
                raise PolicyInputError(f"Missing required field '{field}' at index {idx}")

        amt = float(tx["amount"])
        if amt < 0:
            raise PolicyInputError(f"Negative amount {amt} at index {idx}")

        amounts.append(amt)
        norm_payee = Web3.to_checksum_address(tx["payee"])
        payees.add(norm_payee)

        token = tx.get("token", default_token)
        tokens.add(Web3.to_checksum_address(token))

        timestamps.append(parse_timestamp(tx["timestamp"]))

    timestamps.sort()
    start_time = timestamps[0]
    end_time = timestamps[-1]
    time_span = max(1.0, end_time - start_time)

    # 1. Per-call cap: 95th percentile with safety margin (filters out aberrant spikes)
    p95_amount = percentile(amounts, 0.95)
    per_call_cap = int(math.ceil(max(1.0, p95_amount * safety_margin)))

    # 2. Window duration & call volume
    window_seconds = fixed_window_seconds
    total_calls = len(tx_log)
    call_rate_per_sec = total_calls / time_span
    calls_in_window = call_rate_per_sec * window_seconds
    max_calls_per_window = max(5, int(math.ceil(calls_in_window * safety_margin * 1.5)))

    # 3. Rolling window budget cap
    total_spend = sum(amounts)
    spend_rate_per_sec = total_spend / time_span
    window_expected_spend = spend_rate_per_sec * window_seconds
    window_cap = int(math.ceil(max(float(per_call_cap), window_expected_spend * safety_margin)))

    # 4. Approval threshold
    # Spending above 99th percentile or threshold requires owner co-signature
    p99_amount = percentile(amounts, 0.99)
    approval_threshold = int(math.ceil(p99_amount * approval_multiplier))
    if approval_threshold > window_cap:
        approval_threshold = window_cap

    now = int(time.time())
    expiry = now + session_duration_seconds

    return SessionPolicySpec(
        sessionKey=Web3.to_checksum_address(session_key),
        expiry=expiry,
        perCallCap=per_call_cap,
        windowCap=window_cap,
        windowSeconds=window_seconds,
        maxCallsPerWindow=max_calls_per_window,
        approvalThreshold=approval_threshold,
        requireVerifiedPayee=require_verified_payee,
        allowedPayees=sorted(list(payees)),
        allowedTokens=sorted(list(tokens)),
    )


def main():
    parser = argparse.ArgumentParser(description="KakoroPay EVM Policy Generator")
    parser.add_argument("logfile", nargs="?", help="Path to JSON transaction log")
    parser.add_argument("--session-key", default="0x" + "0" * 40, help="Target session address")
    parser.add_argument("--output", "-o", help="Output path for JSON policy")
    parser.add_argument("--safety-margin", type=float, default=1.25)
    args = parser.parse_args()

    if args.logfile:
        with open(args.logfile, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    policy = score_transactions(
        data,
        session_key=args.session_key,
        safety_margin=args.safety_margin,
    )

    policy_json = policy.model_dump_json(by_alias=True, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(policy_json)
        print(f"Policy written to {args.output}")
    else:
        print(policy_json)


if __name__ == "__main__":
    main()
