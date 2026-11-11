"""On-chain payment proof verification for sellers."""
from __future__ import annotations

from typing import Optional
from dataclasses import dataclass
from web3 import Web3
from hexbytes import HexBytes

from .abi import KAKORO_ACCOUNT_ABI
from .constants import AEVUM_RPC_URL


@dataclass
class VerificationResult:
    valid: bool
    reason: str
    tx_hash: str
    block_number: Optional[int] = None
    payer_account: Optional[str] = None
    session_key: Optional[str] = None
    payee: Optional[str] = None
    token: Optional[str] = None
    amount: Optional[int] = None
    ref: Optional[str] = None


class ReceiptVerifier:
    """Verifies on-chain payment receipts for sellers."""

    def __init__(self, rpc_url: str = AEVUM_RPC_URL, account_address: Optional[str] = None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account_address = Web3.to_checksum_address(account_address) if account_address else None

    def verify_payment(
        self,
        tx_hash: str,
        expected_payee: str,
        expected_token: str,
        min_amount: int,
        expected_ref: str,
        min_confirmations: int = 1,
    ) -> VerificationResult:
        """
        Thoroughly checks that a payment was executed on-chain according to invoice parameters.
        """
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            return VerificationResult(
                valid=False,
                reason=f"Failed to fetch transaction receipt: {e}",
                tx_hash=tx_hash,
            )

        if not receipt:
            return VerificationResult(
                valid=False,
                reason="Transaction receipt not found (pending or dropped)",
                tx_hash=tx_hash,
            )

        if receipt.get("status") != 1:
            return VerificationResult(
                valid=False,
                reason="Transaction reverted on-chain",
                tx_hash=tx_hash,
                block_number=receipt.get("blockNumber"),
            )

        current_block = self.w3.eth.block_number
        tx_block = receipt["blockNumber"]
        confirmations = max(0, current_block - tx_block + 1)

        if confirmations < min_confirmations:
            return VerificationResult(
                valid=False,
                reason=f"Insufficient confirmations: {confirmations} < {min_confirmations}",
                tx_hash=tx_hash,
                block_number=tx_block,
            )

        # Inspect contract events for PaymentExecuted
        contract = self.w3.eth.contract(abi=KAKORO_ACCOUNT_ABI)
        matched_event = None

        norm_expected_payee = Web3.to_checksum_address(expected_payee)
        norm_expected_token = Web3.to_checksum_address(expected_token)
        
        expected_ref_bytes = expected_ref
        if isinstance(expected_ref_bytes, str):
            if not expected_ref_bytes.startswith("0x"):
                expected_ref_bytes = "0x" + expected_ref_bytes
            expected_ref_bytes = HexBytes(expected_ref_bytes)

        for log in receipt.get("logs", []):
            try:
                event = contract.events.PaymentExecuted().process_log(log)
                args = event.args
                # Check target contract if account_address is configured
                if self.account_address and log.address.lower() != self.account_address.lower():
                    continue

                if (
                    HexBytes(args["ref"]) == expected_ref_bytes
                    and Web3.to_checksum_address(args["payee"]) == norm_expected_payee
                    and Web3.to_checksum_address(args["token"]) == norm_expected_token
                    and int(args["amount"]) >= min_amount
                ):
                    matched_event = event
                    break
            except Exception:
                continue

        if not matched_event:
            return VerificationResult(
                valid=False,
                reason="No matching PaymentExecuted event found in transaction logs",
                tx_hash=tx_hash,
                block_number=tx_block,
            )

        args = matched_event.args
        return VerificationResult(
            valid=True,
            reason="Verified on-chain",
            tx_hash=tx_hash,
            block_number=tx_block,
            payer_account=receipt.to,
            session_key=args["sessionKey"],
            payee=args["payee"],
            token=args["token"],
            amount=args["amount"],
            ref=HexBytes(args["ref"]).to_0x_hex(),
        )
