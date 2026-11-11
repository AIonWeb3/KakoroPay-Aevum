// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "./PayeeRegistry.sol";

/**
 * @title KakoroAccount
 * @notice Smart vault with policy-bounded session keys for autonomous AI agents.
 * Designed for the Aevum Builder Challenge on QDay Aevum Testnet (ChainId 44005).
 * Enforces per-call caps, rolling-window budgets, rate limits, token & payee allowlists,
 * optional confirmation-of-payee verification, and dual-signature approval thresholds.
 */
contract KakoroAccount is ReentrancyGuard, Pausable, EIP712 {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;

    struct SessionPolicy {
        uint48 expiry;               // Unix timestamp expiration of session key
        uint256 perCallCap;          // Maximum token amount per single pay() invocation
        uint256 windowCap;           // Maximum token amount spendable within windowSeconds
        uint32 windowSeconds;        // Duration of the rolling window in seconds
        uint32 maxCallsPerWindow;    // Maximum number of pay() calls allowed in windowSeconds
        uint256 approvalThreshold;   // Amounts strictly greater than this require ownerSig co-signature
        bool requireVerifiedPayee;   // If true, payee must be registered in PayeeRegistry
    }

    struct SessionState {
        uint256 spentInWindow;       // Total amount spent in the active rolling window
        uint32 callsInWindow;        // Number of calls in the active rolling window
        uint48 windowStart;          // Timestamp when current rolling window started
    }

    struct PaymentIntent {
        address token;               // ERC-20 payment asset (e.g. tUSD8)
        address payee;               // Destination recipient address
        uint256 amount;              // Payment amount in token units (e.g. 6 decimals)
        bytes32 ref;                 // Invoice identifier / idempotency key
        uint256 deadline;            // Payment validity expiry
        uint256 nonce;               // Sequential replay-prevention nonce for session key
    }

    bytes32 public constant PAYMENT_INTENT_TYPEHASH = keccak256(
        "PaymentIntent(address token,address payee,uint256 amount,bytes32 ref,uint256 deadline,uint256 nonce)"
    );

    address public owner;
    address public payeeRegistry;

    mapping(address => SessionPolicy) public sessionPolicies;
    mapping(address => SessionState) public sessionStates;
    mapping(address => bool) public isSessionActive;

    // sessionKey => (payee => allowed)
    mapping(address => mapping(address => bool)) public isPayeeAllowed;
    // sessionKey => (token => allowed)
    mapping(address => mapping(address => bool)) public isTokenAllowed;
    // sessionKey => current nonce
    mapping(address => uint256) public sessionNonces;

    // ref => whether payment has already been executed (idempotency key)
    mapping(bytes32 => bool) public paidRefs;

    // Custom Errors
    error Unauthorized();
    error ZeroAddress();
    error InvalidPolicy();
    error SessionExpired(uint48 expiry, uint48 current);
    error SessionNotActive(address sessionKey);
    error OverPerCallCap(uint256 amount, uint256 cap);
    error OverWindowBudget(uint256 amount, uint256 remaining);
    error RateLimited(uint32 calls, uint32 maxCalls);
    error TokenNotAllowed(address token);
    error PayeeNotAllowed(address payee);
    error PayeeNotVerified(address payee);
    error ApprovalRequired(uint256 amount, uint256 threshold);
    error RefAlreadyPaid(bytes32 ref);
    error InvalidNonce(uint256 expected, uint256 actual);
    error DeadlineExceeded(uint256 deadline, uint256 current);
    error InvalidSignature();

    // Events
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event PayeeRegistryUpdated(address indexed previousRegistry, address indexed newRegistry);
    event SessionGranted(
        address indexed sessionKey,
        uint48 expiry,
        uint256 perCallCap,
        uint256 windowCap,
        uint32 windowSeconds,
        uint32 maxCallsPerWindow,
        uint256 approvalThreshold,
        bool requireVerifiedPayee
    );
    event SessionRevoked(address indexed sessionKey);
    event PolicyUpdated(address indexed sessionKey);
    event PayeeAllowlistUpdated(address indexed sessionKey, address indexed payee, bool allowed);
    event TokenAllowlistUpdated(address indexed sessionKey, address indexed token, bool allowed);
    event PaymentExecuted(
        bytes32 indexed ref,
        address indexed sessionKey,
        address indexed payee,
        address token,
        uint256 amount
    );
    event Deposited(address indexed token, address indexed sender, uint256 amount);
    event Withdrawn(address indexed token, address indexed to, uint256 amount);

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    constructor(address initialOwner, address initialPayeeRegistry)
        EIP712("KakoroAccount", "1")
    {
        if (initialOwner == address(0)) revert ZeroAddress();
        owner = initialOwner;
        payeeRegistry = initialPayeeRegistry;
        emit OwnershipTransferred(address(0), initialOwner);
        if (initialPayeeRegistry != address(0)) {
            emit PayeeRegistryUpdated(address(0), initialPayeeRegistry);
        }
    }

    // ------------------------------------------------------------------------
    // Owner Administrative Controls
    // ------------------------------------------------------------------------

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setPayeeRegistry(address newRegistry) external onlyOwner {
        emit PayeeRegistryUpdated(payeeRegistry, newRegistry);
        payeeRegistry = newRegistry;
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /**
     * @notice Grants or re-activates a session key with specific policy bounds and token/payee allowlists.
     */
    function grantSession(
        address sessionKey,
        SessionPolicy calldata policy,
        address[] calldata allowedTokens,
        address[] calldata allowedPayees
    ) external onlyOwner {
        if (sessionKey == address(0)) revert ZeroAddress();
        if (policy.expiry <= block.timestamp) revert InvalidPolicy();
        if (policy.perCallCap == 0 || policy.windowCap == 0) revert InvalidPolicy();
        if (policy.windowSeconds == 0 || policy.maxCallsPerWindow == 0) revert InvalidPolicy();
        if (policy.perCallCap > policy.windowCap) revert InvalidPolicy();

        sessionPolicies[sessionKey] = policy;
        isSessionActive[sessionKey] = true;

        // Reset or initialize window state
        sessionStates[sessionKey] = SessionState({
            spentInWindow: 0,
            callsInWindow: 0,
            windowStart: uint48(block.timestamp)
        });

        for (uint256 i = 0; i < allowedTokens.length; i++) {
            isTokenAllowed[sessionKey][allowedTokens[i]] = true;
            emit TokenAllowlistUpdated(sessionKey, allowedTokens[i], true);
        }

        for (uint256 j = 0; j < allowedPayees.length; j++) {
            isPayeeAllowed[sessionKey][allowedPayees[j]] = true;
            emit PayeeAllowlistUpdated(sessionKey, allowedPayees[j], true);
        }

        emit SessionGranted(
            sessionKey,
            policy.expiry,
            policy.perCallCap,
            policy.windowCap,
            policy.windowSeconds,
            policy.maxCallsPerWindow,
            policy.approvalThreshold,
            policy.requireVerifiedPayee
        );
    }

    /**
     * @notice Instantly revokes a session key, preventing any further payment execution.
     */
    function revokeSession(address sessionKey) external onlyOwner {
        isSessionActive[sessionKey] = false;
        emit SessionRevoked(sessionKey);
    }

    /**
     * @notice Updates policy rules for an existing session key.
     */
    function updateSessionPolicy(address sessionKey, SessionPolicy calldata policy) external onlyOwner {
        if (!isSessionActive[sessionKey]) revert SessionNotActive(sessionKey);
        if (policy.expiry <= block.timestamp) revert InvalidPolicy();
        if (policy.perCallCap == 0 || policy.windowCap == 0) revert InvalidPolicy();
        if (policy.windowSeconds == 0 || policy.maxCallsPerWindow == 0) revert InvalidPolicy();
        if (policy.perCallCap > policy.windowCap) revert InvalidPolicy();

        sessionPolicies[sessionKey] = policy;
        emit PolicyUpdated(sessionKey);
    }

    /**
     * @notice Granular allowlist adjustment for payees.
     */
    function setPayeeAllowed(address sessionKey, address payee, bool allowed) external onlyOwner {
        isPayeeAllowed[sessionKey][payee] = allowed;
        emit PayeeAllowlistUpdated(sessionKey, payee, allowed);
    }

    /**
     * @notice Granular allowlist adjustment for tokens.
     */
    function setTokenAllowed(address sessionKey, address token, bool allowed) external onlyOwner {
        isTokenAllowed[sessionKey][token] = allowed;
        emit TokenAllowlistUpdated(sessionKey, token, allowed);
    }

    /**
     * @notice Batch apply policies and allowlists.
     */
    function applyPolicy(
        address sessionKey,
        SessionPolicy calldata policy,
        address[] calldata addTokens,
        address[] calldata removeTokens,
        address[] calldata addPayees,
        address[] calldata removePayees
    ) external onlyOwner {
        if (sessionKey == address(0)) revert ZeroAddress();
        if (policy.expiry <= block.timestamp) revert InvalidPolicy();
        if (policy.perCallCap == 0 || policy.windowCap == 0) revert InvalidPolicy();
        if (policy.windowSeconds == 0 || policy.maxCallsPerWindow == 0) revert InvalidPolicy();
        if (policy.perCallCap > policy.windowCap) revert InvalidPolicy();

        sessionPolicies[sessionKey] = policy;
        isSessionActive[sessionKey] = true;

        for (uint256 i = 0; i < addTokens.length; i++) {
            isTokenAllowed[sessionKey][addTokens[i]] = true;
            emit TokenAllowlistUpdated(sessionKey, addTokens[i], true);
        }
        for (uint256 i = 0; i < removeTokens.length; i++) {
            isTokenAllowed[sessionKey][removeTokens[i]] = false;
            emit TokenAllowlistUpdated(sessionKey, removeTokens[i], false);
        }

        for (uint256 j = 0; j < addPayees.length; j++) {
            isPayeeAllowed[sessionKey][addPayees[j]] = true;
            emit PayeeAllowlistUpdated(sessionKey, addPayees[j], true);
        }
        for (uint256 j = 0; j < removePayees.length; j++) {
            isPayeeAllowed[sessionKey][removePayees[j]] = false;
            emit PayeeAllowlistUpdated(sessionKey, removePayees[j], false);
        }

        emit PolicyUpdated(sessionKey);
    }

    // ------------------------------------------------------------------------
    // Vault Deposit & Withdrawal
    // ------------------------------------------------------------------------

    function deposit(address token, uint256 amount) external nonReentrant {
        if (token == address(0)) revert ZeroAddress();
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        emit Deposited(token, msg.sender, amount);
    }

    function withdraw(address token, address to, uint256 amount) external nonReentrant onlyOwner {
        if (token == address(0) || to == address(0)) revert ZeroAddress();
        IERC20(token).safeTransfer(to, amount);
        emit Withdrawn(token, to, amount);
    }

    // ------------------------------------------------------------------------
    // Payment Execution (Relayed EIP-712 Intent)
    // ------------------------------------------------------------------------

    /**
     * @notice Executes a payment bounded by session policy. Gasless for agent; submitted by any relayer.
     * @param intent The EIP-712 PaymentIntent data struct.
     * @param sessionSig Signature produced by the scoped session key.
     * @param ownerSig Optional co-signature produced by vault owner if amount > approvalThreshold.
     */
    function pay(
        PaymentIntent calldata intent,
        bytes calldata sessionSig,
        bytes calldata ownerSig
    ) external nonReentrant whenNotPaused {
        if (block.timestamp > intent.deadline) {
            revert DeadlineExceeded(intent.deadline, block.timestamp);
        }
        if (paidRefs[intent.ref]) {
            revert RefAlreadyPaid(intent.ref);
        }

        bytes32 digest = getPaymentIntentHash(intent);
        address sessionKey = digest.recover(sessionSig);

        if (!isSessionActive[sessionKey]) {
            revert SessionNotActive(sessionKey);
        }

        SessionPolicy memory policy = sessionPolicies[sessionKey];
        if (block.timestamp >= policy.expiry) {
            revert SessionExpired(policy.expiry, uint48(block.timestamp));
        }

        if (intent.nonce != sessionNonces[sessionKey]) {
            revert InvalidNonce(sessionNonces[sessionKey], intent.nonce);
        }
        sessionNonces[sessionKey]++;

        if (!isTokenAllowed[sessionKey][intent.token]) {
            revert TokenNotAllowed(intent.token);
        }
        if (!isPayeeAllowed[sessionKey][intent.payee]) {
            revert PayeeNotAllowed(intent.payee);
        }

        if (policy.requireVerifiedPayee) {
            if (payeeRegistry == address(0) || !PayeeRegistry(payeeRegistry).isPayeeVerified(intent.payee)) {
                revert PayeeNotVerified(intent.payee);
            }
        }

        if (intent.amount > policy.perCallCap) {
            revert OverPerCallCap(intent.amount, policy.perCallCap);
        }

        // Rolling Window Budget & Rate Limit Check
        SessionState storage state = sessionStates[sessionKey];
        if (block.timestamp >= uint256(state.windowStart) + policy.windowSeconds) {
            state.windowStart = uint48(block.timestamp);
            state.spentInWindow = 0;
            state.callsInWindow = 0;
        }

        if (state.callsInWindow + 1 > policy.maxCallsPerWindow) {
            revert RateLimited(state.callsInWindow + 1, policy.maxCallsPerWindow);
        }

        if (state.spentInWindow + intent.amount > policy.windowCap) {
            revert OverWindowBudget(intent.amount, policy.windowCap - state.spentInWindow);
        }

        // Dual-Signer Approval Threshold Check
        if (policy.approvalThreshold > 0 && intent.amount > policy.approvalThreshold) {
            (address recoveredOwner, ECDSA.RecoverError err, ) = ECDSA.tryRecover(digest, ownerSig);
            if (err != ECDSA.RecoverError.NoError || recoveredOwner != owner) {
                revert ApprovalRequired(intent.amount, policy.approvalThreshold);
            }
        }

        // State Commitments (CEI pattern)
        paidRefs[intent.ref] = true;
        state.spentInWindow += intent.amount;
        state.callsInWindow += 1;

        emit PaymentExecuted(intent.ref, sessionKey, intent.payee, intent.token, intent.amount);

        // Asset Transfer
        IERC20(intent.token).safeTransfer(intent.payee, intent.amount);
    }

    // ------------------------------------------------------------------------
    // View Helpers & Preflight Simulation
    // ------------------------------------------------------------------------

    /**
     * @notice Calculates the EIP-712 digest for a given PaymentIntent.
     */
    function getPaymentIntentHash(PaymentIntent calldata intent) public view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                PAYMENT_INTENT_TYPEHASH,
                intent.token,
                intent.payee,
                intent.amount,
                intent.ref,
                intent.deadline,
                intent.nonce
            )
        );
        return _hashTypedDataV4(structHash);
    }

    /**
     * @notice Inspect remaining budget and calls for an active session in its current window.
     */
    function getBudgetRemaining(address sessionKey)
        external
        view
        returns (uint256 remainingSpend, uint32 remainingCalls, uint48 windowResetTime)
    {
        if (!isSessionActive[sessionKey]) return (0, 0, 0);
        SessionPolicy memory policy = sessionPolicies[sessionKey];
        SessionState memory state = sessionStates[sessionKey];

        if (block.timestamp >= uint256(state.windowStart) + policy.windowSeconds) {
            remainingSpend = policy.windowCap;
            remainingCalls = policy.maxCallsPerWindow;
            windowResetTime = uint48(block.timestamp) + policy.windowSeconds;
        } else {
            remainingSpend = state.spentInWindow >= policy.windowCap ? 0 : policy.windowCap - state.spentInWindow;
            remainingCalls = state.callsInWindow >= policy.maxCallsPerWindow ? 0 : policy.maxCallsPerWindow - state.callsInWindow;
            windowResetTime = state.windowStart + policy.windowSeconds;
        }
    }

    /**
     * @notice Preflight simulation helper to test intent validity without broadcasting.
     */
    function simulatePay(
        PaymentIntent calldata intent,
        bytes calldata sessionSig,
        bytes calldata ownerSig
    ) external view returns (bool allowed, string memory reason) {
        if (paused()) return (false, "Paused");
        if (block.timestamp > intent.deadline) return (false, "DeadlineExceeded");
        if (paidRefs[intent.ref]) return (false, "RefAlreadyPaid");

        bytes32 digest = getPaymentIntentHash(intent);
        (address sessionKey, ECDSA.RecoverError err, ) = ECDSA.tryRecover(digest, sessionSig);
        if (err != ECDSA.RecoverError.NoError) return (false, "InvalidSignature");

        if (!isSessionActive[sessionKey]) return (false, "SessionNotActive");

        SessionPolicy memory policy = sessionPolicies[sessionKey];
        if (block.timestamp >= policy.expiry) return (false, "SessionExpired");
        if (intent.nonce != sessionNonces[sessionKey]) return (false, "InvalidNonce");
        if (!isTokenAllowed[sessionKey][intent.token]) return (false, "TokenNotAllowed");
        if (!isPayeeAllowed[sessionKey][intent.payee]) return (false, "PayeeNotAllowed");

        if (policy.requireVerifiedPayee) {
            if (payeeRegistry == address(0) || !PayeeRegistry(payeeRegistry).isPayeeVerified(intent.payee)) {
                return (false, "PayeeNotVerified");
            }
        }

        if (intent.amount > policy.perCallCap) return (false, "OverPerCallCap");

        SessionState memory state = sessionStates[sessionKey];
        uint256 currentSpent = state.spentInWindow;
        uint32 currentCalls = state.callsInWindow;

        if (block.timestamp >= uint256(state.windowStart) + policy.windowSeconds) {
            currentSpent = 0;
            currentCalls = 0;
        }

        if (currentCalls + 1 > policy.maxCallsPerWindow) return (false, "RateLimited");
        if (currentSpent + intent.amount > policy.windowCap) return (false, "OverWindowBudget");

        if (policy.approvalThreshold > 0 && intent.amount > policy.approvalThreshold) {
            (address recoveredOwner, ECDSA.RecoverError ownerErr, ) = ECDSA.tryRecover(digest, ownerSig);
            if (ownerErr != ECDSA.RecoverError.NoError || recoveredOwner != owner) {
                return (false, "ApprovalRequired");
            }
        }

        if (IERC20(intent.token).balanceOf(address(this)) < intent.amount) {
            return (false, "InsufficientVaultBalance");
        }

        return (true, "OK");
    }
}
