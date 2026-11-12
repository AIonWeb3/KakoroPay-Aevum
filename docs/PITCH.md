# KakoroPay: Pitch Deck Outline & 3-Minute Live Demo Narration

> **Submission for the Aevum Builder Challenge #1 on QDay Aevum Testnet (Chain ID: 44005)**  
> *Track: Infrastructure & Agent Economy*

---

## 1. Executive Pitch Outline

### 1.1 The Problem
Autonomous AI agents powered by LLMs (LangChain, AutoGen, CrewAI, MCP) need to purchase digital resources: API calls, data feeds, GPU inference, and cloud compute. Today, developers face a dangerous dilemma:
1. **Unsafe Private Keys:** Giving an LLM direct custody of a private key or loaded wallet invites catastrophe. Prompt injection attacks, rogue looping, or compromised endpoints can drain a treasury in milliseconds.
2. **Heavyweight Account Abstraction:** ERC-4337 is powerful but often unavailable or immature on emerging EVM chains. QDay Aevum Testnet currently has no public bundler or native paymaster.
3. **No Facilitator for x402:** Standard HTTP 402 protocols lack decentralized, facilitator-free micropayment execution on high-speed L2s.

### 1.2 The Solution: KakoroPay
KakoroPay provides **least-privilege, data-derived on-chain spend policies with gasless session keys** for autonomous AI agents on the QDay Aevum Testnet:
- **Zero-Gas, Zero-Balance Session Keys:** Agents hold ephemeral ECDSA session keys with 0 native gas and 0 token balance.
- **On-Chain Policy Bounds:** Bounded by rolling-window caps, per-call caps, rate limits, token/payee allowlists, and dual-signature approval thresholds enforced directly by `KakoroAccount.sol`.
- **Data-Derived Limits:** Policies are automatically generated from historic transaction logs using $p_{95} \times \text{margin}$ outlier rejection to eliminate aberrant spikes.
- **Gasless Relayer:** Relayers submit EIP-712 typed intents (`PaymentIntent`) and pay gas, while agents remain zero-cost to manage.
- **Instant Revocation & Pause:** Human vault owners can revoke compromised session keys or pause the entire vault in a single transaction.

### 1.3 Target Audience & Users
1. **AI Agent Developers & Teams:** Developers deploying autonomous agents needing programmatic micropayments without balance loss risks.
2. **Merchants & API Providers:** SaaS providers, data vendors, and AI model hosts wanting to monetize per-request using HTTP 402 without subscription friction.
3. **Autonomous DAO Treasuries:** Organizations delegating operational budgets to automated bot operators.

### 1.4 Business Model Options
- **B2B Enterprise Agent Guard:** SaaS subscription for automated policy generation, anomaly detection, and centralized console monitoring.
- **Gasless Relayer Fee Margin:** Adding a tiny flat surcharge (e.g., 0.1% or 0.001 tUSD8) on relayed micropayments for sponsoring gas.
- **Merchant Gateway Protocol Fee:** Optional settlement fee for instant on-chain invoice confirmation and receipt attestations.

### 1.5 Path to Mainnet
1. **Audit & Formal Verification:** Certora / OpenZeppelin audit of `KakoroAccount.sol` and `PayeeRegistry.sol`.
2. **ERC-4337 Convergence:** When QDay launches native paymasters and bundlers, adapt `PaymentIntent` into UserOperations seamlessly.
3. **Multi-Asset Support:** Expand allowlists to support multiple stablecoins and native wrapped tokens.
4. **Post-Quantum Bonus Track:** Integrate ML-DSA-65 post-quantum signing anchors for invoice receipts.

---

## 2. 3-Minute Live Demo Script & Narration Guide

**Total Duration:** 3:00  
**Presenter:** Single speaker with screen sharing running `python demo/run_demo.py` alongside the Blockscout explorer and Operator Console.

```
+------------------------------------------------------------------------+
| Timeline | Stage / Screen             | Narration Script               |
+------------------------------------------------------------------------+
| 0:00-0:30| Slide / Terminal           | Problem Hook & Agent Identity  |
| 0:30-1:15| Policy Gen & 402 Challenge | Data-Derived Guardrails        |
| 1:15-2:00| EIP-712 Signing & Relaying | Zero-Gas Settlement on Aevum   |
| 2:00-2:30| Verification & Data Delivery| Merchant Verification          |
| 2:30-3:00| Security Circuit Breakers  | Edge Cases & Instant Revoke    |
+------------------------------------------------------------------------+
```

### [0:00 – 0:30] Hook & Identity Setup
* **Visual:** Terminal showing command execution and generated keys.
* **Narration:**
  > *"Autonomous AI agents are beginning to transact economically, but giving an LLM access to a private key is a massive security hazard. Prompt injection or an unhandled infinite loop can wipe out an entire wallet in seconds.*
  > 
  > *Welcome to KakoroPay on QDay Aevum Testnet. Today, we demonstrate an end-to-end autonomous payment flow where an agent pays for high-value intelligence using a zero-fund, zero-gas session key bounded by an immutable smart contract."*

### [0:30 – 1:15] Data-Derived Spend Policy & 402 Challenge
* **Visual:** Terminal output of Step 2 & Step 3.
* **Narration:**
  > *"Instead of guessing spend limits, KakoroPay derives policies from historical logs. Notice here: a malicious 50 tUSD8 spike occurred in the agent's history. Our policy engine runs 95th-percentile filtering, automatically rejects the outlier, and caps the agent at 1.25 tUSD8 per call with an active rolling window budget and strict rate limit.*
  > 
  > *Now, the agent attempts to fetch premium market intelligence from a merchant API. The server immediately returns an HTTP 402 Payment Required challenge with a unique 32-byte invoice reference on Aevum Chain ID 44005."*

### [1:15 – 2:00] EIP-712 Intent Signing & Gasless Relay
* **Visual:** EIP-712 signature generated and transaction submitted. Show Blockscout explorer link.
* **Narration:**
  > *"The agent's session key holds 0 gas and 0 tokens. It cannot be robbed. It simply signs an EIP-712 PaymentIntent specifying the payee, amount, expiry, and invoice ID.*
  > 
  > *Our gasless relayer picks up the intent, validates it via preflight simulation, and submits it to KakoroAccount on Aevum Testnet. Because Aevum has sub-second to 1-second block times, confirmation is virtually instantaneous. Here is the live transaction hash on the Aevum Blockscout explorer."*

### [2:00 – 2:30] Merchant Verification & Data Delivery
* **Visual:** Step 6 and Step 7 showing HTTP 200 OK and data response payload.
* **Narration:**
  > *"The agent retries the merchant request with payment proof. The merchant's on-chain verifier inspects the PaymentExecuted event on Aevum: confirming the recipient, token, amount, and invoice idempotency.*
  > 
  > *Verification passes in 50 milliseconds! The merchant returns HTTP 200 with the protected alpha intelligence payload. The invoice is marked settled, making replay attacks mathematically impossible."*

### [2:30 – 3:00] Circuit Breakers & Instant Revocation
* **Visual:** Step 8 showing contract reverts and revocation event.
* **Narration:**
  > *"What happens under attack? Let's test the guardrails:*
  > 1. *If prompt injection tricks the agent into spending 10 tUSD8, the contract immediately halts the transaction with OverPerCallCap.*
  > 2. *If an attacker tries to replay an old receipt, the contract reverts with RefAlreadyPaid.*
  > 3. *And if the human owner detects suspicious activity, a single click emits SessionRevoked. Instantly, all subsequent attempts fail at zero cost to the owner.*
  > 
  > *KakoroPay unlocks secure, policy-bounded autonomy for the agent economy on QDay Aevum. Thank you!"*
