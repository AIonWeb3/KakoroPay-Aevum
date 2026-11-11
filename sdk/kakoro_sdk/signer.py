"""EIP-712 message formatting and signing for KakoroPay."""
from __future__ import annotations

from typing import Union
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3
from hexbytes import HexBytes

from .constants import (
    AEVUM_CHAIN_ID,
    EIP712_DOMAIN_NAME,
    EIP712_DOMAIN_VERSION,
    PAYMENT_INTENT_TYPES,
)
from .types import PaymentIntent


def build_eip712_payload(
    verifying_contract: str,
    intent: PaymentIntent,
    chain_id: int = AEVUM_CHAIN_ID,
) -> dict:
    """Builds the complete EIP-712 data dictionary."""
    ref_bytes = intent.ref
    if isinstance(ref_bytes, str):
        if not ref_bytes.startswith("0x"):
            ref_bytes = "0x" + ref_bytes
        ref_bytes = HexBytes(ref_bytes)

    return {
        "types": PAYMENT_INTENT_TYPES,
        "primaryType": "PaymentIntent",
        "domain": {
            "name": EIP712_DOMAIN_NAME,
            "version": EIP712_DOMAIN_VERSION,
            "chainId": chain_id,
            "verifyingContract": Web3.to_checksum_address(verifying_contract),
        },
        "message": {
            "token": Web3.to_checksum_address(intent.token),
            "payee": Web3.to_checksum_address(intent.payee),
            "amount": int(intent.amount),
            "ref": ref_bytes,
            "deadline": int(intent.deadline),
            "nonce": int(intent.nonce),
        },
    }


def sign_payment_intent(
    verifying_contract: str,
    intent: PaymentIntent,
    private_key: str,
    chain_id: int = AEVUM_CHAIN_ID,
) -> str:
    """
    Signs an EIP-712 PaymentIntent with the given private key.
    
    Returns:
        Hex-encoded signature string (with 0x prefix).
    """
    payload = build_eip712_payload(verifying_contract, intent, chain_id)
    structured_msg = encode_typed_data(full_message=payload)
    signed = Account.sign_message(structured_msg, private_key=private_key)
    return signed.signature.to_0x_hex()
