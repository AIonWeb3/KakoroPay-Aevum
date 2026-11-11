"""Data models and typed structures for KakoroPay."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict


class PaymentRequirements(BaseModel):
    """x402 payment requirements returned in HTTP 402."""
    model_config = ConfigDict(populate_by_name=True)

    x402_version: int = Field(default=2, alias="x402Version")
    scheme: str = "exact"
    network: str = "eip155:44005"
    asset: str
    pay_to: str = Field(alias="payTo")
    amount: int
    invoice_id: str = Field(alias="invoiceId")
    max_timeout_seconds: int = Field(default=300, alias="maxTimeoutSeconds")


class PaymentIntent(BaseModel):
    """EIP-712 PaymentIntent struct for KakoroAccount."""
    token: str
    payee: str
    amount: int
    ref: str  # Hex string (0x-prefixed 32 bytes)
    deadline: int
    nonce: int


class PaymentProof(BaseModel):
    """Payment proof submitted to seller on retry."""
    model_config = ConfigDict(populate_by_name=True)

    tx_hash: str = Field(alias="txHash")
    invoice_id: str = Field(alias="invoiceId")
    account: Optional[str] = None


class SessionBudget(BaseModel):
    """Current remaining budget for a session key."""
    remaining_spend: int
    remaining_calls: int
    window_reset_time: int
    is_active: bool
