# KakoroPay Agent Payment Scaffold (QDay Aevum Testnet)

This template shows how to equip an autonomous AI agent (LangChain, AutoGen, CrewAI, FastMCP) with gasless, policy-bounded micropayments on the QDay Aevum Testnet (Chain ID 44005).

---

## 5-Minute Quickstart

### 1. Installation
Install dependencies:
```bash
pip install -r requirements.txt
# Or install kakoro-sdk directly from source:
pip install -e ../sdk
```

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in your deployed vault address:
```bash
AEVUM_RPC_URL=https://rpc-test.qday.info
KAKORO_ACCOUNT_ADDRESS=0xYourDeployedVaultAddress
RELAYER_URL=http://127.0.0.1:8002
```

### 3. Granting the Agent a Session Policy
Before running the agent, the vault owner must grant the agent's session key an active policy:
```python
from kakoro_policy.generator import score_transactions, to_apply_policy_calldata

# Feed agent historic logs to derive caps
policy = score_transactions(historical_tx_log, session_key=agent_session_address)

# View human-readable summary
print(explain(policy))

# Apply policy on-chain via owner wallet or operator console
```

### 4. Running the Agent
Run the agent script:
```bash
python agent_pay.py
```

The agent will automatically:
1. Hit the protected endpoint (`/api/premium-data`).
2. Intercept the `HTTP 402 Payment Required` challenge.
3. Validate invoice details (amount, asset, payee) against local safety limits.
4. Sign an EIP-712 `PaymentIntent` using its 0-gas session key.
5. Transmit the intent to the relayer.
6. Retry the request with the on-chain payment proof and retrieve the paid payload.
