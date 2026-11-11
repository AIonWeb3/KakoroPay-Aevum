# KakoroPay Port Map: Soroban -> EVM (Aevum Testnet)

This document provides a comprehensive mapping from the original Soroban/Stellar KakoroPay (AgentPay) codebase to the EVM implementation for the Aevum Builder Challenge #1 on the QDay Aevum Testnet (chainId 44005).

---

## 1. High-Level Architectural Mapping

| Component | Soroban (Stellar) Implementation | EVM (QDay Aevum) Implementation | Status |
| :--- | :--- | :--- | :--- |
| **Smart Account** | `agent-account` in Rust with `stellar-accounts` context rules & auth | `KakoroAccount.sol` in Solidity ^0.8.24 (OpenZeppelin SafeERC20, EIP712, ECDSA) | **Rewrite** |
| **Confirmation of Payee** | Custom Soroban registry / in-contract payee binding | `PayeeRegistry.sol` standalone confirmation-of-payee contract | **Rewrite** |
| **Execution Model** | `__check_auth` invocation on SAC `transfer` | EIP-712 signed `PaymentIntent` relayed to `pay()` | **Rewrite** |
| **MCP Server** | Rust MCP server (`mcp-server/src`) | Python MCP server (`mcp-server/`) via official `mcp` SDK + `web3.py` | **Rewrite** (Python-first) |
| **Payer Worker** | TypeScript worker (`payer/`) | Python/TS worker (`payer/`) signing EIP-712 session intents | **Rewrite** |
| **Seller API** | Express/TS mock & x402 resource server (`tests/e2e/src/seller.ts`) | FastAPI 402 seller (`seller/`) with on-chain EVM receipt verification | **Rewrite** (Python-first) |
| **Policy Generator** | Python (`policy-generator/`) with ledger sequences | Python (`policy-generator/`) with block timestamps, tUSD8 units (6 dec) | **Keep & Adapt** |
| **Console UI** | FastAPI + Vanilla JS (`demo/`) | FastAPI + Vanilla JS (`console/`) with live EVM Blockscout timeline | **Keep & Adapt** |
| **Client SDK** | Internal helpers | Standalone `kakoro-sdk` Python package (pip-installable) | **New Extraction** |
| **Solidity Module** | N/A | Foundry-installable library for policy-bound accounts | **New Extraction** |

---

## 2. Smart Contract Porting Details

### 2.1 Soroban `agent-account` vs EVM `KakoroAccount`

In Soroban, smart accounts implement `CustomAccountInterface` with `__check_auth`, and OpenZeppelin's `stellar-accounts` executes context rules that inspect invocation arguments (e.g. `transfer(from, to, amount)`).

On EVM (QDay Aevum Testnet):
- Accounts are standard ECDSA externally-owned addresses or smart contracts.
- EntryPoint v0.7 is available on chain, but as established in chain reconnaissance, a direct **EIP-712 scoped session intent + relayer** pattern is cleaner, facilitator-free, gasless for the agent, and has zero dependency on 4337 bundlers.

```
       [AI Agent]
           │
           │ (1) Signs EIP-712 PaymentIntent using scoped Session Key
           ▼
       [Relayer]
           │
           │ (2) Calls KakoroAccount.pay(intent, sessionSig, ownerSig)
           ▼
    [KakoroAccount] (Vault)
      ├── 1. Validates Session Key & Expiry
      ├── 2. Enforces Per-Call & Rolling Window Spend Caps
      ├── 3. Validates Rate Limits (calls per window)
      ├── 4. Checks Token & Payee Allowlist
      ├── 5. Checks PayeeRegistry (if required)
      ├── 6. Checks ApprovalThreshold (requires ownerSig if exceeded)
      ├── 7. Prevents Replay (unique ref / nonce)
      └── 8. SafeERC20.safeTransfer(payee, amount)
           │
           ▼
      [tUSD8 Token] (0x456569838f1d43009A91ebA4263147Afd7233483)
```

### 2.2 Data Structures & Storage Mapping

| Soroban Data Structure | EVM Solidity Equivalent |
| :--- | :--- |
| `DataKey::Admin` | `address public owner;` |
| `SpendPolicyParams` / `PolicyKey::SpendCap` | `struct SessionPolicy { uint48 expiry; uint256 perCallCap; uint256 windowCap; uint32 windowSeconds; uint32 maxCallsPerWindow; uint256 approvalThreshold; bool requireVerifiedPayee; }` |
| `PolicyKey::Spent`, `Calls`, `LastReset` | `struct SessionState { uint256 spentInWindow; uint32 callsInWindow; uint48 windowStart; }` |
| `AllowedPayee { asset, pay_to, ... }` | `mapping(address => mapping(address => bool)) public isPayeeAllowed;` (session -> (payee -> bool)) and token allowlist |
| `InvoiceAnchor` / Replay prevention | `mapping(bytes32 => bool) public paidRefs;` (ensures `ref` / `invoiceId` paid at most once) |
| Nonces | `mapping(address => uint256) public sessionNonces;` (sequential or bitmap) |

### 2.3 EIP-712 Typed Data Specification

```solidity
struct PaymentIntent {
    address token;
    address payee;
    uint256 amount;
    bytes32 ref;       // invoiceId / payment reference (idempotency key)
    uint256 deadline;  // unix timestamp expiry
    uint256 nonce;     // session key nonce
}
```

Domain Separator:
- `name`: "KakoroAccount"
- `version`: "1"
- `chainId`: 44005 (0xabe5)
- `verifyingContract`: `address(this)`

### 2.4 Error Codes Mapping

Soroban contract errors are mapped 1-to-1 to EVM custom errors (gas-efficient, informative reverts):

| Soroban Error (`AgentAccountError`) | EVM Custom Error (`KakoroAccount`) | Description |
| :--- | :--- | :--- |
| `Unauthorized` | `Unauthorized()` | Sender is not owner or valid relayer/signer |
| `AlreadyInitialized` | `AlreadyInitialized()` | Initializer re-entry |
| `EmptyPolicy` | `InvalidPolicy()` | Cap or parameters invalid |
| *N/A (new)* | `SessionExpired(uint48 expiry, uint48 current)` | Current block timestamp > session expiry |
| `OverBudget` | `OverPerCallCap(uint256 amount, uint256 cap)` | Payment exceeds per-call maximum |
| `OverBudget` | `OverWindowBudget(uint256 amount, uint256 remaining)` | Spend exceeds remaining budget in window |
| `RateLimited` | `RateLimited(uint32 calls, uint32 maxCalls)` | Call frequency exceeded in window |
| `InvalidContext` | `PayeeNotAllowed(address payee)` | Recipient not on session allowlist |
| `InvalidContext` | `PayeeNotVerified(address payee)` | Payee not verified in `PayeeRegistry` |
| *N/A (new)* | `ApprovalRequired(uint256 amount, uint256 threshold)` | Amount > threshold and owner signature missing |
| *N/A (new)* | `RefAlreadyPaid(bytes32 ref)` | Payment reference already executed |
| *N/A (new)* | `InvalidNonce(uint256 expected, uint256 actual)` | Intent nonce mismatch |
| *N/A (new)* | `DeadlineExceeded(uint256 deadline, uint256 current)` | Payment intent expired |
| *N/A (new)* | `Paused()` | Contract or session is paused |

### 2.5 Events

```solidity
event SessionGranted(address indexed sessionKey, uint48 expiry, uint256 perCallCap, uint256 windowCap);
event SessionRevoked(address indexed sessionKey);
event PolicyUpdated(address indexed sessionKey);
event PaymentExecuted(
    bytes32 indexed ref,
    address indexed sessionKey,
    address indexed payee,
    address token,
    uint256 amount
);
event AccountPaused(address indexed account);
event AccountUnpaused(address indexed account);
```

---

## 3. Off-Chain Components Mapping

### 3.1 MCP Server (`mcp-server/`)
- **Language**: Python 3.11+ using the official `mcp` SDK (`mcp.server`).
- **Tools**:
  - `discover_resources(catalog_url)`: fetches available merchant payment endpoints with strict SSRF defense.
  - `check_budget(session_key)`: queries `KakoroAccount` on-chain for remaining window budget, rate limits, and caps.
  - `pay_and_call(resource_url, method, params)`: full flow: executes HTTP request, handles 402 Payment Required, preflights against policy, triggers intent signing, broadcasts via relayer, waits for receipt, and completes the paid request.
- **SSRF Defense Rules (Ported from Rust `mcp-server/src/main.rs`)**:
  - URL scheme must be `http` or `https` (configurable HTTPS-only in production).
  - Resolve DNS and block private / loopback / link-local / cloud metadata ranges:
    - `127.0.0.0/8` (loopback)
    - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (RFC1918)
    - `169.254.0.0/16` (Link-local, AWS/GCP metadata `169.254.169.254`)
    - `::1`, `fc00::/7`, `fe80::/10` (IPv6 equivalents)
  - HTTP redirects disabled or strictly re-validated on every hop.
  - Strict 5s connection / 10s total timeout, 1MB max response body.

### 3.2 Payer Service (`payer/`)
- Isolated signer service.
- Holds the session private key; never exposes the key to the MCP server.
- Receives payment request `{token, payee, amount, ref, deadline}`, validates against local constraints, creates EIP-712 signature, and returns the signature to be broadcast by the relayer.

### 3.3 Seller Service (`seller/`)
- FastAPI application mimicking standard HTTP 402 flow.
- When an unpaid request arrives at a protected endpoint (e.g. `/api/weather`):
  - Returns `402 Payment Required` with `PAYMENT-REQUIRED` header / JSON body:
    ```json
    {
      "x402Version": 2,
      "scheme": "exact",
      "network": "eip155:44005",
      "asset": "0x456569838f1d43009A91ebA4263147Afd7233483",
      "payTo": "0x...",
      "amount": "1000000",
      "invoiceId": "0x...",
      "maxTimeoutSeconds": 300
    }
    ```
- When a retry arrives with `PAYMENT-SIGNATURE` / `{txHash, invoiceId}`:
  - Seller queries QDay RPC, verifies transaction receipt, verifies that event `PaymentExecuted` was emitted with matching `ref == invoiceId`, `payee == sellerAddress`, `amount >= requiredAmount`, and sufficient confirmations.
  - Returns HTTP 200 with data.

### 3.4 Policy Generator (`policy-generator/`)
- Ported from Python Soroban version (`generate_policy.py`).
- Consumes resource pricing data & usage traffic patterns.
- Calculates per-call caps, window caps, and time windows (in seconds).
- Generates JSON formatted policy ready for `grantSession` or `applyPolicy`.

### 3.5 Operator Console (`console/`)
- FastAPI backend with WebSockets or SSE for real-time chain events.
- Vanilla JS frontend with zero build step (no complex bundler).
- Features:
  - Account balance & active sessions display.
  - Live timeline of on-chain `PaymentExecuted`, `SessionGranted`, and `SessionRevoked` events.
  - Direct Blockscout explorer links (`https://explorer-test.qday.info/tx/...`).
  - One-click buttons: "Revoke Session", "Pause Vault", "Unpause Vault".

---

## 4. Summary of Dropped vs New Components

| Dropped from Soroban | Reason |
| :--- | :--- |
| `stellar-accounts` Context Rules crate | Soroban-specific account framework replaced with standard EIP-712 intent verification in Solidity. |
| Ledger sequence window tracking | Replaced with standard EVM `block.timestamp`. |
| Rust MCP server | Rewritten in Python as requested by the user ("experienced Python developer, default to Python for off-chain code"). |

| Added for EVM / Aevum | Reason |
| :--- | :--- |
| `PayeeRegistry.sol` | Confirmation-of-payee attestation registry. |
| `KakoroAccount.sol` with EIP-712 | Native EVM session key validation and gasless relayer support. |
| `kakoro-sdk` Python package | Reusable Python client for 402 payments on Aevum. |
| Standalone Solidity Module | Foundry package exportable for other Aevum builders. |
