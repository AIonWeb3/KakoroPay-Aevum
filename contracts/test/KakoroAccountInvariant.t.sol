// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/KakoroAccount.sol";
import "../src/PayeeRegistry.sol";
import "../src/MockERC20.sol";

contract KakoroAccountHandler is Test {
    KakoroAccount public account;
    MockERC20 public token;
    address public owner;
    uint256 public ownerPk;
    address public sessionKey;
    uint256 public sessionPk;
    address public seller1;
    address public seller2;
    address public untrustedPayee;

    uint256 public totalPaid;
    uint256 public successfulCalls;
    uint256 public currentNonce;

    constructor(
        KakoroAccount _account,
        MockERC20 _token,
        address _owner,
        uint256 _ownerPk,
        address _sessionKey,
        uint256 _sessionPk,
        address _seller1,
        address _seller2,
        address _untrustedPayee
    ) {
        account = _account;
        token = _token;
        owner = _owner;
        ownerPk = _ownerPk;
        sessionKey = _sessionKey;
        sessionPk = _sessionPk;
        seller1 = _seller1;
        seller2 = _seller2;
        untrustedPayee = _untrustedPayee;
    }

    function payPayment(uint256 amountSeed, uint256 payeeSeed, uint256 warpSeed) external {
        // Warp between 0 and 3 days
        uint256 warpTime = warpSeed % (3 days);
        vm.warp(block.timestamp + warpTime);

        // Pick payee: 40% seller1, 40% seller2, 20% untrustedPayee
        address payee;
        uint256 p = payeeSeed % 5;
        if (p < 2) payee = seller1;
        else if (p < 4) payee = seller2;
        else payee = untrustedPayee;

        // Bounded amount: between 1 and 200 tUSD8
        uint256 amount = ((amountSeed % 200) + 1) * 1e6;

        bytes32 ref = keccak256(abi.encodePacked("invariant-ref-", currentNonce, block.timestamp));
        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: payee,
            amount: amount,
            ref: ref,
            deadline: block.timestamp + 1 hours,
            nonce: currentNonce
        });

        bytes32 digest = account.getPaymentIntentHash(intent);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(sessionPk, digest);
        bytes memory sessionSig = abi.encodePacked(r, s, v);

        bytes memory ownerSig = "";
        if (amount > 50 * 1e6) {
            (uint8 ov, bytes32 or, bytes32 os) = vm.sign(ownerPk, digest);
            ownerSig = abi.encodePacked(or, os, ov);
        }

        try account.pay(intent, sessionSig, ownerSig) {
            totalPaid += amount;
            successfulCalls++;
            currentNonce++;
        } catch {
            // Expected policy or cap reverts
        }
    }
}

contract KakoroAccountInvariantTest is Test {
    KakoroAccount public account;
    PayeeRegistry public registry;
    MockERC20 public token;
    KakoroAccountHandler public handler;

    uint256 internal ownerPk = 0xA11CE;
    address internal owner;
    uint256 internal sessionPk = 0xB0B;
    address internal sessionKey;

    address internal seller1 = address(0x5E11E21);
    address internal seller2 = address(0x5E11E22);
    address internal untrustedPayee = address(0xBAD);

    function setUp() public {
        owner = vm.addr(ownerPk);
        sessionKey = vm.addr(sessionPk);

        vm.startPrank(owner);
        registry = new PayeeRegistry(owner);
        account = new KakoroAccount(owner, address(registry));
        token = new MockERC20("Test USD8", "tUSD8", 6);

        token.mint(owner, 10_000_000 * 1e6);
        token.approve(address(account), type(uint256).max);
        account.deposit(address(token), 1_000_000 * 1e6); // 1M tUSD8 vault balance

        KakoroAccount.SessionPolicy memory policy = KakoroAccount.SessionPolicy({
            expiry: uint48(block.timestamp + 30 days),
            perCallCap: 100 * 1e6,         // 100 tUSD8 per call
            windowCap: 500 * 1e6,          // 500 tUSD8 per window
            windowSeconds: 1 days,         // 1-day rolling window
            maxCallsPerWindow: 20,         // 20 calls per window
            approvalThreshold: 50 * 1e6,   // Co-sign > 50 tUSD8
            requireVerifiedPayee: false
        });

        address[] memory tokens = new address[](1);
        tokens[0] = address(token);

        address[] memory payees = new address[](2);
        payees[0] = seller1;
        payees[1] = seller2;

        account.grantSession(sessionKey, policy, tokens, payees);
        vm.stopPrank();

        handler = new KakoroAccountHandler(
            account,
            token,
            owner,
            ownerPk,
            sessionKey,
            sessionPk,
            seller1,
            seller2,
            untrustedPayee
        );

        targetContract(address(handler));
    }

    /// @notice Invariant: Untrusted payee NEVER receives any token balance
    function invariant_UntrustedPayeeNeverReceivesFunds() public view {
        assertEq(token.balanceOf(untrustedPayee), 0, "Untrusted payee received funds");
    }

    /// @notice Invariant: Vault balance + total paid = initial deposit
    function invariant_VaultSolvencyAndConservation() public view {
        uint256 currentBalance = token.balanceOf(address(account));
        uint256 sellersBalance = token.balanceOf(seller1) + token.balanceOf(seller2);
        assertEq(currentBalance + sellersBalance, 1_000_000 * 1e6, "Conservation violated");
    }

    /// @notice Invariant: Active window spent never exceeds windowCap (500 tUSD8)
    function invariant_ActiveWindowSpentNeverExceedsCap() public view {
        (uint256 spent, , ) = account.sessionStates(sessionKey);
        assertLe(spent, 500 * 1e6, "Spent in window exceeded cap");
    }
}
