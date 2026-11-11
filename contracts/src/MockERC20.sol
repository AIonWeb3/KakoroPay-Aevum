// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

/**
 * @title MockERC20
 * @notice Test token matching tUSD8 (6 decimals, EIP-2612 permit support).
 */
contract MockERC20 is ERC20, ERC20Permit {
    uint8 private immutable _decimals;

    constructor(string memory name, string memory symbol, uint8 decimals_)
        ERC20(name, symbol)
        ERC20Permit(name)
    {
        _decimals = decimals_;
    }

    function decimals() public view virtual override returns (uint8) {
        return _decimals;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
