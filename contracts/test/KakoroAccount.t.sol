// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/KakoroAccount.sol";
import "../src/PayeeRegistry.sol";
import "../src/MockERC20.sol";

contract KakoroAccountTest is Test {
    KakoroAccount public account;
    PayeeRegistry public registry;
    MockERC20 public token;

    uint256 internal ownerPk = 0xA11CE;
    address internal owner;

    uint256 internal sessionPk = 0xB0B;
    address internal sessionKey;

    uint256 internal relayerPk = 0xCAFE;
    address internal relayer;

    address internal seller1 = address(0x5E11E21);
    address internal seller2 = address(0x5E11E22);
    address internal untrustedPayee = address(0xBAD);

    KakoroAccount.SessionPolicy internal defaultPolicy;

    function setUp() public {
        owner = vm.addr(ownerPk);
        sessionKey = vm.addr(sessionPk);
        relayer = vm.addr(relayerPk);

        vm.startPrank(owner);
        registry = new PayeeRegistry(owner);
        account = new KakoroAccount(owner, address(registry));
        token = new MockERC20("Test USD8", "tUSD8", 6);

        // Mint tokens to owner and deposit into KakoroAccount vault
        token.mint(owner, 1_000_000 * 1e6);
        token.approve(address(account), type(uint256).max);
        account.deposit(address(token), 100_000 * 1e6); // 100k tUSD8
        vm.stopPrank();

        defaultPolicy = KakoroAccount.SessionPolicy({
            expiry: uint48(block.timestamp + 7 days),
            perCallCap: 100 * 1e6,         // 100 tUSD8 per call
            windowCap: 500 * 1e6,          // 500 tUSD8 per window
            windowSeconds: 1 days,         // 1-day rolling window
            maxCallsPerWindow: 10,         // 10 calls per day
            approvalThreshold: 50 * 1e6,   // Calls > 50 tUSD8 require owner signature
            requireVerifiedPayee: false
        });
    }

    function _grantDefaultSession() internal {
        address[] memory tokens = new address[](1);
        tokens[0] = address(token);

        address[] memory payees = new address[](2);
        payees[0] = seller1;
        payees[1] = seller2;

        vm.prank(owner);
        account.grantSession(sessionKey, defaultPolicy, tokens, payees);
    }

    function _signIntent(
        KakoroAccount.PaymentIntent memory intent,
        uint256 signerPk
    ) internal view returns (bytes memory) {
        bytes32 digest = account.getPaymentIntentHash(intent);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerPk, digest);
        return abi.encodePacked(r, s, v);
    }

    // ------------------------------------------------------------------------
    // Unit Tests: Administrative Functions
    // ------------------------------------------------------------------------

    function test_InitialState() public view {
        assertEq(account.owner(), owner);
        assertEq(account.payeeRegistry(), address(registry));
        assertEq(token.balanceOf(address(account)), 100_000 * 1e6);
    }

    function test_OwnerWithdraw() public {
        vm.prank(owner);
        account.withdraw(address(token), owner, 10_000 * 1e6);
        assertEq(token.balanceOf(address(account)), 90_000 * 1e6);
        assertEq(token.balanceOf(owner), 910_000 * 1e6);
    }

    function test_NonOwnerCannotWithdraw() public {
        vm.prank(relayer);
        vm.expectRevert(KakoroAccount.Unauthorized.selector);
        account.withdraw(address(token), relayer, 1_000 * 1e6);
    }

    function test_GrantAndRevokeSession() public {
        _grantDefaultSession();
        assertTrue(account.isSessionActive(sessionKey));
        assertTrue(account.isPayeeAllowed(sessionKey, seller1));
        assertTrue(account.isTokenAllowed(sessionKey, address(token)));

        // Revoke
        vm.prank(owner);
        account.revokeSession(sessionKey);
        assertFalse(account.isSessionActive(sessionKey));
    }

    function test_PauseAndUnpause() public {
        _grantDefaultSession();
        vm.prank(owner);
        account.pause();
        assertTrue(account.paused());

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-pause-1"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });
        bytes memory sig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(abi.encodeWithSignature("EnforcedPause()"));
        account.pay(intent, sig, "");

        vm.prank(owner);
        account.unpause();
        assertFalse(account.paused());
    }

    // ------------------------------------------------------------------------
    // Unit Tests: Successful Payment Execution
    // ------------------------------------------------------------------------

    function test_SuccessfulPaymentUnderApprovalThreshold() public {
        _grantDefaultSession();

        uint256 amount = 20 * 1e6; // 20 tUSD8 (< 50 tUSD8 approvalThreshold)
        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: amount,
            ref: keccak256("inv-success-1"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        uint256 sellerBalanceBefore = token.balanceOf(seller1);
        uint256 vaultBalanceBefore = token.balanceOf(address(account));

        vm.prank(relayer);
        vm.expectEmit(true, true, true, true);
        emit KakoroAccount.PaymentExecuted(intent.ref, sessionKey, seller1, address(token), amount);
        account.pay(intent, sessionSig, "");

        assertEq(token.balanceOf(seller1), sellerBalanceBefore + amount);
        assertEq(token.balanceOf(address(account)), vaultBalanceBefore - amount);
        assertTrue(account.paidRefs(intent.ref));
        assertEq(account.sessionNonces(sessionKey), 1);
    }

    function test_SuccessfulPaymentWithOwnerCoSignature() public {
        _grantDefaultSession();

        uint256 amount = 80 * 1e6; // 80 tUSD8 (> 50 tUSD8 threshold, but <= 100 cap)
        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: amount,
            ref: keccak256("inv-dual-1"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);
        bytes memory ownerSig = _signIntent(intent, ownerPk);

        vm.prank(relayer);
        account.pay(intent, sessionSig, ownerSig);

        assertEq(token.balanceOf(seller1), amount);
    }

    // ------------------------------------------------------------------------
    // Unit Tests: Safety & Policy Revert Checks
    // ------------------------------------------------------------------------

    function test_RevertOverApprovalThresholdWithoutOwnerSig() public {
        _grantDefaultSession();

        uint256 amount = 60 * 1e6; // > 50 threshold
        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: amount,
            ref: keccak256("inv-dual-missing"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KakoroAccount.ApprovalRequired.selector,
                amount,
                defaultPolicy.approvalThreshold
            )
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertOverPerCallCap() public {
        _grantDefaultSession();

        uint256 amount = 150 * 1e6; // > 100 perCallCap
        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: amount,
            ref: keccak256("inv-over-call-cap"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KakoroAccount.OverPerCallCap.selector,
                amount,
                defaultPolicy.perCallCap
            )
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertRefAlreadyPaid_Idempotent() public {
        _grantDefaultSession();

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-idempotent-1"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        // First execution succeeds
        vm.prank(relayer);
        account.pay(intent, sessionSig, "");

        // Duplicate execution with identical ref must revert RefAlreadyPaid
        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(KakoroAccount.RefAlreadyPaid.selector, intent.ref)
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertNonAllowlistedPayee() public {
        _grantDefaultSession();

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: untrustedPayee,
            amount: 10 * 1e6,
            ref: keccak256("inv-untrusted-payee"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(KakoroAccount.PayeeNotAllowed.selector, untrustedPayee)
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertExpiredDeadline() public {
        _grantDefaultSession();

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-expired-deadline"),
            deadline: block.timestamp - 1, // in the past
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KakoroAccount.DeadlineExceeded.selector,
                intent.deadline,
                block.timestamp
            )
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertExpiredSession() public {
        _grantDefaultSession();

        // Warp past session expiry (7 days)
        vm.warp(block.timestamp + 8 days);

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-expired-session"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KakoroAccount.SessionExpired.selector,
                defaultPolicy.expiry,
                uint48(block.timestamp)
            )
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertRevokedSession() public {
        _grantDefaultSession();

        vm.prank(owner);
        account.revokeSession(sessionKey);

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-revoked-session"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });

        bytes memory sessionSig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(KakoroAccount.SessionNotActive.selector, sessionKey)
        );
        account.pay(intent, sessionSig, "");
    }

    function test_RevertOverWindowBudget() public {
        _grantDefaultSession(); // windowCap = 500 tUSD8, perCallCap = 100 tUSD8

        // Spend 5 x 100 = 500 tUSD8 (using ownerSig since 100 > 50 threshold)
        for (uint256 i = 0; i < 5; i++) {
            KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
                token: address(token),
                payee: seller1,
                amount: 100 * 1e6,
                ref: keccak256(abi.encodePacked("inv-budget-fill-", i)),
                deadline: block.timestamp + 1 hours,
                nonce: i
            });
            bytes memory sessionSig = _signIntent(intent, sessionPk);
            bytes memory ownerSig = _signIntent(intent, ownerPk);
            vm.prank(relayer);
            account.pay(intent, sessionSig, ownerSig);
        }

        // 6th call exceeds windowCap (remaining = 0)
        KakoroAccount.PaymentIntent memory intent6 = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-budget-overflow"),
            deadline: block.timestamp + 1 hours,
            nonce: 5
        });
        bytes memory sessionSig6 = _signIntent(intent6, sessionPk);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KakoroAccount.OverWindowBudget.selector,
                10 * 1e6,
                0
            )
        );
        account.pay(intent6, sessionSig6, "");
    }

    function test_RollingWindowResetAllowsSpendingAgain() public {
        _grantDefaultSession();

        // Spend 500 tUSD8 to exhaust window budget
        for (uint256 i = 0; i < 5; i++) {
            KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
                token: address(token),
                payee: seller1,
                amount: 100 * 1e6,
                ref: keccak256(abi.encodePacked("inv-reset-fill-", i)),
                deadline: block.timestamp + 1 hours,
                nonce: i
            });
            vm.prank(relayer);
            account.pay(intent, _signIntent(intent, sessionPk), _signIntent(intent, ownerPk));
        }

        // Warp past window duration (1 day)
        vm.warp(block.timestamp + 1 days + 1 seconds);

        // Payment should now succeed in the new rolling window!
        KakoroAccount.PaymentIntent memory newIntent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 20 * 1e6,
            ref: keccak256("inv-new-window"),
            deadline: block.timestamp + 1 hours,
            nonce: 5
        });
        vm.prank(relayer);
        account.pay(newIntent, _signIntent(newIntent, sessionPk), "");
        assertEq(token.balanceOf(seller1), 520 * 1e6);
    }

    function test_PayeeRegistryVerificationRequirement() public {
        // Create session requiring verified payee
        defaultPolicy.requireVerifiedPayee = true;
        _grantDefaultSession();

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 10 * 1e6,
            ref: keccak256("inv-registry-check"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });
        bytes memory sig = _signIntent(intent, sessionPk);

        // Fails because seller1 is not registered in PayeeRegistry
        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(KakoroAccount.PayeeNotVerified.selector, seller1)
        );
        account.pay(intent, sig, "");

        // Register seller1 in PayeeRegistry
        vm.prank(owner);
        registry.registerPayee(seller1, keccak256("seller1-org"));

        // Now succeeds!
        vm.prank(relayer);
        account.pay(intent, sig, "");
        assertEq(token.balanceOf(seller1), 10 * 1e6);
    }

    function test_SimulatePayHelper() public {
        _grantDefaultSession();

        KakoroAccount.PaymentIntent memory validIntent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 20 * 1e6,
            ref: keccak256("sim-valid"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });
        bytes memory validSig = _signIntent(validIntent, sessionPk);

        (bool allowed, string memory reason) = account.simulatePay(validIntent, validSig, "");
        assertTrue(allowed);
        assertEq(reason, "OK");

        // Over cap simulation
        KakoroAccount.PaymentIntent memory invalidIntent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: 200 * 1e6,
            ref: keccak256("sim-over-cap"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });
        bytes memory invalidSig = _signIntent(invalidIntent, sessionPk);

        (bool allowed2, string memory reason2) = account.simulatePay(invalidIntent, invalidSig, "");
        assertFalse(allowed2);
        assertEq(reason2, "OverPerCallCap");
    }

    // ------------------------------------------------------------------------
    // Fuzz Testing: Invariants & Robustness
    // ------------------------------------------------------------------------

    function testFuzz_SpendNeverExceedsPerCallCap(uint256 amount) public {
        vm.assume(amount > defaultPolicy.perCallCap && amount < type(uint128).max);
        _grantDefaultSession();

        KakoroAccount.PaymentIntent memory intent = KakoroAccount.PaymentIntent({
            token: address(token),
            payee: seller1,
            amount: amount,
            ref: keccak256("fuzz-cap"),
            deadline: block.timestamp + 1 hours,
            nonce: 0
        });
        bytes memory sig = _signIntent(intent, sessionPk);

        vm.prank(relayer);
        vm.expectRevert();
        account.pay(intent, sig, "");
    }
}
