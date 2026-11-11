// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title PayeeRegistry
 * @notice Confirmation-of-payee registry for KakoroPay smart accounts.
 * Allows an owner / designated attester to register and attest to verified payee addresses.
 */
contract PayeeRegistry {
    address public owner;
    
    // payee => verified status
    mapping(address => bool) private _verifiedPayees;
    // payee => name / identity hash
    mapping(address => bytes32) private _payeeNameHashes;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event PayeeRegistered(address indexed payee, bytes32 indexed nameHash);
    event PayeeRevoked(address indexed payee);

    error Unauthorized();
    error ZeroAddress();

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert ZeroAddress();
        owner = initialOwner;
        emit OwnershipTransferred(address(0), initialOwner);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    /**
     * @notice Registers or updates a verified payee with its identity hash.
     */
    function registerPayee(address payee, bytes32 nameHash) external onlyOwner {
        if (payee == address(0)) revert ZeroAddress();
        _verifiedPayees[payee] = true;
        _payeeNameHashes[payee] = nameHash;
        emit PayeeRegistered(payee, nameHash);
    }

    /**
     * @notice Batch registers multiple payees.
     */
    function registerPayeesBatch(address[] calldata payees, bytes32[] calldata nameHashes) external onlyOwner {
        require(payees.length == nameHashes.length, "Mismatched arrays");
        for (uint256 i = 0; i < payees.length; i++) {
            if (payees[i] == address(0)) revert ZeroAddress();
            _verifiedPayees[payees[i]] = true;
            _payeeNameHashes[payees[i]] = nameHashes[i];
            emit PayeeRegistered(payees[i], nameHashes[i]);
        }
    }

    /**
     * @notice Revokes a payee's verification.
     */
    function revokePayee(address payee) external onlyOwner {
        _verifiedPayees[payee] = false;
        emit PayeeRevoked(payee);
    }

    /**
     * @notice Checks if a payee is currently verified.
     */
    function isPayeeVerified(address payee) external view returns (bool) {
        return _verifiedPayees[payee];
    }

    /**
     * @notice Retrieves the registered name/identity hash for a payee.
     */
    function getPayeeNameHash(address payee) external view returns (bytes32) {
        return _payeeNameHashes[payee];
    }
}
