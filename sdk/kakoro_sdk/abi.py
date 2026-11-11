"""Contract ABIs for KakoroAccount, PayeeRegistry, and ERC20."""

KAKORO_ACCOUNT_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "token", "type": "address"},
                    {"internalType": "address", "name": "payee", "type": "address"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "bytes32", "name": "ref", "type": "bytes32"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "nonce", "type": "uint256"},
                ],
                "internalType": "struct KakoroAccount.PaymentIntent",
                "name": "intent",
                "type": "tuple",
            },
            {"internalType": "bytes", "name": "sessionSig", "type": "bytes"},
            {"internalType": "bytes", "name": "ownerSig", "type": "bytes"},
        ],
        "name": "pay",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "token", "type": "address"},
                    {"internalType": "address", "name": "payee", "type": "address"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "bytes32", "name": "ref", "type": "bytes32"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "nonce", "type": "uint256"},
                ],
                "internalType": "struct KakoroAccount.PaymentIntent",
                "name": "intent",
                "type": "tuple",
            },
            {"internalType": "bytes", "name": "sessionSig", "type": "bytes"},
            {"internalType": "bytes", "name": "ownerSig", "type": "bytes"},
        ],
        "name": "simulatePay",
        "outputs": [
            {"internalType": "bool", "name": "allowed", "type": "bool"},
            {"internalType": "string", "name": "reason", "type": "string"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "sessionKey", "type": "address"}],
        "name": "getBudgetRemaining",
        "outputs": [
            {"internalType": "uint256", "name": "remainingSpend", "type": "uint256"},
            {"internalType": "uint32", "name": "remainingCalls", "type": "uint32"},
            {"internalType": "uint48", "name": "windowResetTime", "type": "uint48"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "sessionNonces",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "isSessionActive",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "paidRefs",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "paused",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "ref", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "sessionKey", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "payee", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "PaymentExecuted",
        "type": "event",
    },
]

ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"},
        ],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
