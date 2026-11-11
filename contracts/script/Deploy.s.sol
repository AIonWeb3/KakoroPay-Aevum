// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/PayeeRegistry.sol";
import "../src/KakoroAccount.sol";

contract DeployKakoroPay is Script {
    function run() external returns (address registryAddr, address accountAddr) {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        console.log("Deploying KakoroPay to chain ID:", block.chainid);
        console.log("Deployer address:", deployer);

        vm.startBroadcast(deployerPrivateKey);

        // 1. Deploy PayeeRegistry
        PayeeRegistry registry = new PayeeRegistry(deployer);
        console.log("PayeeRegistry deployed at:", address(registry));

        // 2. Deploy KakoroAccount
        KakoroAccount account = new KakoroAccount(deployer, address(registry));
        console.log("KakoroAccount deployed at:", address(account));

        vm.stopBroadcast();

        registryAddr = address(registry);
        accountAddr = address(account);
    }
}
