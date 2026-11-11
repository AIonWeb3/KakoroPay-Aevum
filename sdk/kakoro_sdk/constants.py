"""Constants and network configuration for KakoroPay on Aevum Testnet."""

AEVUM_CHAIN_ID = 44005
AEVUM_RPC_URL = "https://rpc-test.qday.info"
AEVUM_EXPLORER_URL = "https://explorer-test.qday.info"
DEFAULT_TUSD8_ADDRESS = "0x456569838f1d43009A91ebA4263147Afd7233483"

# EIP-712 Domain configuration for KakoroAccount
EIP712_DOMAIN_NAME = "KakoroAccount"
EIP712_DOMAIN_VERSION = "1"

# Type hashes and specifications
PAYMENT_INTENT_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "PaymentIntent": [
        {"name": "token", "type": "address"},
        {"name": "payee", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "ref", "type": "bytes32"},
        {"name": "deadline", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
    ],
}
