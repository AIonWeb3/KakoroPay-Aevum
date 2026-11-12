"""
Policy Evaluation Harness for KakoroPay.

Replays benign and adversarial transaction traces against a candidate spend policy
and measures False-Block Rate (FBR) and Attack-Block Rate (ABR).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from web3 import Web3

from .schema import SessionPolicySpec
from .generator import parse_timestamp


@dataclass
class EvaluationResult:
    total_benign: int
    benign_passed: int
    benign_blocked: int
    false_block_rate: float

    total_attacks: int
    attacks_blocked: int
    attacks_passed: int
    attack_block_rate: float

    reasons: Dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "============================================================",
            "          KAKOROPAY POLICY EVALUATION REPORT",
            "============================================================",
            f"Benign Transactions:   {self.total_benign}",
            f"  ├─ Allowed:           {self.benign_passed}",
            f"  └─ False Blocks:      {self.benign_blocked} (FBR: {self.false_block_rate:.2%})",
            "",
            f"Adversarial Attacks:   {self.total_attacks}",
            f"  ├─ Blocked (Success): {self.attacks_blocked} (ABR: {self.attack_block_rate:.2%})",
            f"  └─ Passed (Breach):   {self.attacks_passed}",
            "",
            "Denial Reasons Breakdown:",
        ]
        if not self.reasons:
            lines.append("  (No transactions blocked)")
        for reason, count in sorted(self.reasons.items(), key=lambda x: -x[1]):
            lines.append(f"  • {reason:<22}: {count}")
        lines.append("============================================================")
        return "\n".join(lines)


class PolicySimulator:
    """Simulates on-chain KakoroAccount policy verification logic."""

    def __init__(self, spec: SessionPolicySpec, initial_timestamp: Optional[float] = None):
        self.spec = spec
        self.window_start = float(initial_timestamp or time.time())
        self.spent_in_window = 0
        self.calls_in_window = 0
        self.allowed_tokens = {Web3.to_checksum_address(t) for t in spec.allowed_tokens}
        self.allowed_payees = {Web3.to_checksum_address(p) for p in spec.allowed_payees}

    def evaluate_transaction(self, tx: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Evaluates a transaction. Returns (allowed: bool, reason: str).
        """
        ts = parse_timestamp(tx.get("timestamp", time.time()))
        amount = int(tx["amount"])
        token = Web3.to_checksum_address(tx.get("token", list(self.allowed_tokens)[0] if self.allowed_tokens else "0x" + "0" * 40))
        payee = Web3.to_checksum_address(tx["payee"])

        # 1. Expiry check
        if ts >= self.spec.expiry:
            return False, "SessionExpired"

        # 2. Token allowlist
        if self.allowed_tokens and token not in self.allowed_tokens:
            return False, "TokenNotAllowed"

        # 3. Payee allowlist
        if self.allowed_payees and payee not in self.allowed_payees:
            return False, "PayeeNotAllowed"

        # 4. Per-call cap
        if amount > self.spec.per_call_cap:
            return False, "OverPerCallCap"

        # 5. Rolling window check & reset
        if ts >= self.window_start + self.spec.window_seconds:
            self.window_start = ts
            self.spent_in_window = 0
            self.calls_in_window = 0

        # 6. Rate limit
        if self.calls_in_window + 1 > self.spec.max_calls_per_window:
            return False, "RateLimited"

        # 7. Window budget
        if self.spent_in_window + amount > self.spec.window_cap:
            return False, "OverWindowBudget"

        # Commit state
        self.spent_in_window += amount
        self.calls_in_window += 1
        return True, "OK"


def evaluate_policy(
    spec: SessionPolicySpec,
    benign_txs: List[Dict[str, Any]],
    attack_txs: List[Dict[str, Any]],
) -> EvaluationResult:
    """
    Evaluates benign and adversarial transactions against the policy spec.
    """
    all_timestamps = [parse_timestamp(tx.get("timestamp", time.time())) for tx in benign_txs + attack_txs]
    start_ts = min(all_timestamps) if all_timestamps else time.time()

    sim = PolicySimulator(spec, initial_timestamp=start_ts)
    reasons: Dict[str, int] = {}

    benign_passed = 0
    benign_blocked = 0
    for tx in benign_txs:
        allowed, reason = sim.evaluate_transaction(tx)
        if allowed:
            benign_passed += 1
        else:
            benign_blocked += 1
            reasons[reason] = reasons.get(reason, 0) + 1

    # Reset simulator for attack replay to simulate fresh attacks against active window
    sim_attack = PolicySimulator(spec, initial_timestamp=start_ts)
    attacks_blocked = 0
    attacks_passed = 0
    for tx in attack_txs:
        allowed, reason = sim_attack.evaluate_transaction(tx)
        if allowed:
            attacks_passed += 1
        else:
            attacks_blocked += 1
            reasons[reason] = reasons.get(reason, 0) + 1

    total_benign = len(benign_txs)
    total_attacks = len(attack_txs)
    fbr = (benign_blocked / total_benign) if total_benign > 0 else 0.0
    abr = (attacks_blocked / total_attacks) if total_attacks > 0 else 1.0

    return EvaluationResult(
        total_benign=total_benign,
        benign_passed=benign_passed,
        benign_blocked=benign_blocked,
        false_block_rate=fbr,
        total_attacks=total_attacks,
        attacks_blocked=attacks_blocked,
        attacks_passed=attacks_passed,
        attack_block_rate=abr,
        reasons=reasons,
    )


def generate_benchmark_traces(payee_allowed: str, token_allowed: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Generates synthetic benign traces and typical agent attack vectors."""
    now = time.time()
    benign = []
    # 20 typical small micropayment calls over 30 minutes
    for i in range(20):
        benign.append({
            "payee": payee_allowed,
            "token": token_allowed,
            "amount": 1_000_000 + (i % 3) * 100_000,  # 1.0 to 1.2 tUSD8
            "timestamp": now - 1800 + i * 90,
        })

    # Attack vectors specifically targeting policy limits
    attacks = [
        # 1. Prompt Injection treasury drain (huge amount > perCallCap)
        {
            "payee": payee_allowed,
            "token": token_allowed,
            "amount": 500_000_000,  # 500 tUSD8 (per-call cap is ~1.5 tUSD8)
            "timestamp": now + 10,
            "type": "treasury_drain_spike",
        },
        # 2. Exfiltration to attacker payee
        {
            "payee": "0x" + "bad0" * 10,
            "token": token_allowed,
            "amount": 1_000_000,
            "timestamp": now + 20,
            "type": "unauthorized_payee",
        },
        # 3. Rogue token drain
        {
            "payee": payee_allowed,
            "token": "0x" + "dead" * 10,
            "amount": 1_000_000,
            "timestamp": now + 30,
            "type": "unauthorized_token",
        },
        # 4. Expired session attack
        {
            "payee": payee_allowed,
            "token": token_allowed,
            "amount": 1_000_000,
            "timestamp": now + 86400 * 30,  # Far in the future
            "type": "expired_session",
        },
        # 5. Out-of-bounds per-call spike
        {
            "payee": payee_allowed,
            "token": token_allowed,
            "amount": 10_000_000,  # 10 tUSD8 > 1.25 tUSD8 cap
            "timestamp": now + 40,
            "type": "over_per_call_cap",
        },
        # 6. Secondary unauthorized payee attempt
        {
            "payee": "0x" + "c001" * 10,
            "token": token_allowed,
            "amount": 2_000_000,
            "timestamp": now + 50,
            "type": "unauthorized_payee_secondary",
        },
    ]

    return benign, attacks


def main():
    parser = argparse.ArgumentParser(description="KakoroPay Policy Evaluation Harness")
    parser.add_argument("--policy", help="Path to JSON policy file")
    parser.add_argument("--benign", help="Path to benign transactions JSON")
    parser.add_argument("--attacks", help="Path to attack transactions JSON")
    args = parser.parse_args()

    payee = "0x" + "1" * 40
    token = "0x456569838f1d43009A91ebA4263147Afd7233483"

    if args.benign and args.attacks and args.policy:
        with open(args.policy, "r", encoding="utf-8") as f:
            spec = SessionPolicySpec.model_validate_json(f.read())
        with open(args.benign, "r", encoding="utf-8") as f:
            benign_data = json.load(f)
        with open(args.attacks, "r", encoding="utf-8") as f:
            attack_data = json.load(f)
    else:
        # Default benchmark
        from .generator import score_transactions
        benign_data, attack_data = generate_benchmark_traces(payee, token)
        spec = score_transactions(benign_data, session_key="0x" + "2" * 40, default_token=token)

    result = evaluate_policy(spec, benign_data, attack_data)
    print(result.summary())


if __name__ == "__main__":
    main()
