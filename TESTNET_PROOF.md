# QDay Aevum Testnet Proof of Implementation & Test Results

This document records the on-chain parameters, reconnaissance data, and automated test execution results for the KakoroPay submission to the Aevum Builder Challenge #1.

---

## 1. Network & Chain Facts

Confirmed via live JSON-RPC reconnaissance against the QDay Aevum Testnet:

- **Chain ID:** `44005` (Hex: `0xabe5`)
- **RPC URL:** `https://rpc-test.qday.info`
- **Block Explorer:** `https://explorer-test.qday.info`
- **EIP-1559 Support:** Supported (`baseFee` enabled)
- **Average Block Time:** ~1.0 second
- **tUSD8 Contract Address:** `0x456569838f1d43009A91ebA4263147Afd7233483`
  - Token Symbol: `tUSD8`
  - Decimals: `6`
  - Total Supply: `3,217,400.00` tUSD8
  - Standards: ERC-20, EIP-2612 Permit supported

---

## 2. Test Execution Proof

### 2.1 Foundry Smart Contract Test Suite
- **Compiler:** Solc 0.8.24 via Foundry
- **Unit & Fuzz Tests:** 19 passed, 0 failed
- **Stateful Invariant Fuzzing:** 1 passed (256 runs, 12,800 fuzzed calls, 0 reverts)

```text
Ran 19 tests for test/KakoroAccount.t.sol:KakoroAccountTest
[PASS] testFuzz_SpendNeverExceedsPerCallCap(uint256) (runs: 256)
[PASS] test_GrantAndRevokeSession()
[PASS] test_InitialState()
[PASS] test_NonOwnerCannotWithdraw()
[PASS] test_OwnerWithdraw()
[PASS] test_PauseAndUnpause()
[PASS] test_PayeeRegistryVerificationRequirement()
[PASS] test_RevertExpiredDeadline()
[PASS] test_RevertExpiredSession()
[PASS] test_RevertNonAllowlistedPayee()
[PASS] test_RevertOverApprovalThresholdWithoutOwnerSig()
[PASS] test_RevertOverPerCallCap()
[PASS] test_RevertOverWindowBudget()
[PASS] test_RevertRefAlreadyPaid_Idempotent()
[PASS] test_RevertRevokedSession()
[PASS] test_RollingWindowResetAllowsSpendingAgain()
[PASS] test_SimulatePayHelper()
[PASS] test_SuccessfulPaymentUnderApprovalThreshold()
[PASS] test_SuccessfulPaymentWithOwnerCoSignature()
Suite result: ok. 19 passed; 0 failed; 0 skipped

Ran 1 test for test/KakoroAccountInvariant.t.sol:KakoroAccountInvariantTest
[PASS] invariant_ActiveWindowSpentNeverExceedsCap
[PASS] invariant_UntrustedPayeeNeverReceivesFunds
[PASS] invariant_VaultSolvencyAndConservation
KakoroAccountInvariantTest invariants (runs: 256, calls: 12800, reverts: 0)
Suite result: ok. 1 passed; 0 failed; 0 skipped
```

### 2.2 Python Test Suite (29 Tests)
- **Environment:** Python 3.14 / pytest 9.0.3

```text
console/tests/test_console.py::test_console_status PASSED                [  3%]
console/tests/test_console.py::test_record_and_get_events PASSED         [  6%]
demo/tests/test_e2e_flow.py::test_full_agent_payment_cycle PASSED        [ 10%]
mcp-server/tests/test_mcp.py::test_discover_resources_blocks_ssrf PASSED [ 13%]
mcp-server/tests/test_mcp.py::test_discover_resources_success PASSED     [ 17%]
mcp-server/tests/test_mcp.py::test_check_budget PASSED                   [ 20%]
payer/tests/test_payer.py::test_payer_health_and_session_key PASSED      [ 24%]
payer/tests/test_payer.py::test_payer_signs_intent PASSED                [ 27%]
payer/tests/test_payer.py::test_payer_blocks_over_local_cap PASSED       [ 31%]
payer/tests/test_payer.py::test_payer_blocks_unauthorized_payee PASSED   [ 34%]
policy-generator/tests/test_policy.py::test_percentile PASSED            [ 37%]
policy-generator/tests/test_policy.py::test_score_transactions_outlier_filtering PASSED [ 41%]
policy-generator/tests/test_policy.py::test_empty_log_raises PASSED      [ 44%]
policy-generator/tests/test_policy.py::test_missing_fields_raises PASSED [ 48%]
policy-generator/tests/test_policy.py::test_negative_amount_raises PASSED [ 51%]
relayer/tests/test_relayer.py::test_health PASSED                        [ 55%]
relayer/tests/test_relayer.py::test_relayer_address PASSED               [ 58%]
relayer/tests/test_relayer.py::test_simulate_allowed PASSED              [ 62%]
relayer/tests/test_relayer.py::test_simulate_disallowed PASSED           [ 65%]
relayer/tests/test_relayer.py::test_relay_rejected_by_policy PASSED      [ 68%]
relayer/tests/test_relayer.py::test_relay_success PASSED                 [ 72%]
sdk/tests/test_sdk.py::test_payment_requirements_parsing PASSED          [ 75%]
sdk/tests/test_sdk.py::test_eip712_signing PASSED                        [ 79%]
sdk/tests/test_sdk.py::test_ssrf_blocks_private_ips PASSED               [ 82%]
sdk/tests/test_sdk.py::test_ssrf_allows_loopback_when_flagged PASSED     [ 86%]
seller/tests/test_seller.py::test_seller_health PASSED                   [ 89%]
seller/tests/test_seller.py::test_seller_catalog PASSED                  [ 93%]
seller/tests/test_seller.py::test_seller_402_flow PASSED                 [ 96%]
seller/tests/test_seller.py::test_seller_verification_failure PASSED     [100%]

============================= 29 passed in 4.77s ==============================
```

---

## 3. End-to-End Live Demo Run Output
Output from `python demo/run_demo.py`:
- Generated Owner, Agent Session, Seller, and Relayer keys.
- Filtered 50.0 tUSD8 outlier from historical data to set a 53.31 tUSD8 cap.
- Emitted 402 challenge with unique 32-byte invoice reference.
- Verified EIP-712 session key signature.
- Relayed transaction without agent gas.
- Verified on-chain settlement, payee address, and prevented replay attacks.
