# Feedback for QDay Aevum Testnet Infrastructure & DevEx

During the porting and implementation of KakoroPay for the Aevum Builder Challenge #1, we performed thorough chain reconnaissance and testing against the QDay Aevum Testnet. Here is constructive feedback for the QDay engineering and developer relations teams.

---

## 1. What Went Well

1. **Fast Block Times (~1.0s):** Transaction confirmation latency is exceptionally fast. For autonomous agent micropayments where agents need rapid feedback before invoking downstream APIs, sub-second to 1-second block inclusion is a huge competitive advantage over slower EVM L2s.
2. **Standard EVM & RPC Compatibility:** The JSON-RPC implementation strictly adhered to Ethereum standards (`eth_chainId`, `eth_blockNumber`, `eth_estimateGas`, `eth_getLogs`). EIP-1559 Type-2 transactions functioned smoothly.
3. **EIP-2612 Permit Support on tUSD8:** The testnet `tUSD8` token contract supports EIP-2612 permits, which enables gasless token approvals and deposits into smart accounts.
4. **Blockscout Explorer Integration:** Having a functioning Blockscout instance (`https://explorer-test.qday.info`) allows immediate visual inspection of contract events and transaction receipts.

---

## 2. Opportunities for Improvement

1. **RPC Rate Limits & Node Connection Stability:**
   - Under bursts of rapid polling during integration testing, occasional connection timeouts were observed on `https://rpc-test.qday.info`. Adding a WebSocket endpoint (`wss://...`) for event subscriptions would significantly reduce HTTP polling overhead for agent relayers and console dashboards.
2. **Blockscout Contract Verification API:**
   - While the explorer UI works well, programmatically verifying Solidity contracts via standard Foundry `forge verify-contract` requires custom configuration due to non-standard Blockscout API routing or rate-limiting. Clearer documentation on recommended `foundry.toml` verification endpoints for QDay would be beneficial.
3. **Faucet Automation & Rate Limits:**
   - The web faucet (`https://faucet.qday.info/en`) is protected by web challenge checks, which is great for anti-abuse, but making a developer API key or authenticated faucet endpoint available for automated CI/CD pipelines would streamline automated testnet integration runs.
4. **Official RPC Documentation for Account Abstraction:**
   - Chain recon confirmed `EntryPoint v0.7` (`0x0000000071727De22E5E9d8BAf0edAc6f37da032`) exists on-chain. However, documentation regarding whether the network operates a public ERC-4337 bundler or paymaster was not found. Clarifying official bundler support will help builders deciding between ERC-4337 UserOps and EIP-712 session intents.

---

## 3. Conclusion

The QDay Aevum Testnet provides a performant, low-fee EVM environment well-suited for autonomous agent micro-economies and high-frequency settlement protocols like KakoroPay.
