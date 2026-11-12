"""Unit tests for KakoroPay Policy Generator."""
import pytest
from datetime import datetime, timezone, timedelta

from kakoro_policy.generator import score_transactions, PolicyInputError, percentile


def test_percentile():
    data = [10, 20, 30, 40, 50]
    assert percentile(data, 0.5) == 30
    assert percentile(data, 0.0) == 10
    assert percentile(data, 1.0) == 50


def test_score_transactions_outlier_filtering():
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    payee = "0x" + "1" * 40

    tx_log = []
    # 20 steady 1 tUSD8 payments (1,000,000 stroops)
    for i in range(20):
        tx_log.append({
            "payee": payee,
            "amount": 1_000_000,
            "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
        })

    # 1 anomalous spike
    tx_log.append({
        "payee": payee,
        "amount": 100_000_000,
        "timestamp": (base_time + timedelta(minutes=20)).isoformat(),
    })

    policy = score_transactions(tx_log, safety_margin=1.25)

    # p95 of 20 x 1_000_000 and 1 x 100_000_000 is 1_000_000
    # perCallCap with 1.25 safety margin should be 1_250_000
    assert policy.per_call_cap == 1_250_000
    assert policy.per_call_cap < 100_000_000
    assert policy.allowed_payees == [payee]
    assert policy.max_calls_per_window >= 21


def test_empty_log_raises():
    with pytest.raises(PolicyInputError):
        score_transactions([])


def test_missing_fields_raises():
    with pytest.raises(PolicyInputError):
        score_transactions([{"payee": "0x" + "1" * 40}])


def test_negative_amount_raises():
    with pytest.raises(PolicyInputError):
        score_transactions([{
            "payee": "0x" + "1" * 40,
            "amount": -50,
            "timestamp": 1234567,
        }])


def test_explain_and_calldata():
    from kakoro_policy.generator import explain, to_apply_policy_calldata
    payee = "0x" + "1" * 40
    tx_log = [{"payee": payee, "amount": 1_000_000, "timestamp": 1000}]
    policy = score_transactions(tx_log, session_key="0x" + "2" * 40)

    # 1. Test explain
    explanation = explain(policy)
    assert "KAKOROPAY SESSION POLICY EXPLANATION" in explanation
    assert "Per-Call Maximum" in explanation
    assert payee in explanation

    # 2. Test calldata generation
    calldata = to_apply_policy_calldata(policy)
    assert isinstance(calldata, str)
    assert calldata.startswith("0x")
    assert len(calldata) > 100


def test_eval_harness():
    from kakoro_policy.eval_harness import generate_benchmark_traces, evaluate_policy
    payee = "0x" + "1" * 40
    token = "0x456569838f1d43009A91ebA4263147Afd7233483"

    benign, attacks = generate_benchmark_traces(payee, token)
    policy = score_transactions(benign, session_key="0x" + "2" * 40, default_token=token)

    result = evaluate_policy(policy, benign, attacks)
    assert result.total_benign == len(benign)
    assert result.total_attacks == len(attacks)
    assert result.false_block_rate == 0.0  # None of the normal benign payments should be blocked
    assert result.attack_block_rate > 0.90  # >90% of attacks blocked
    assert "OverPerCallCap" in result.reasons
    assert "PayeeNotAllowed" in result.reasons

