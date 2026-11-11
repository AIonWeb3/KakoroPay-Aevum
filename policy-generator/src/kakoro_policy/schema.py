"""Schema models for EVM Session Policy specification."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class SessionPolicySpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_key: str = Field(alias="sessionKey")
    expiry: int = Field(description="Unix timestamp expiry (uint48)")
    per_call_cap: int = Field(alias="perCallCap", description="Max raw amount per individual call")
    window_cap: int = Field(alias="windowCap", description="Max raw spend per rolling window")
    window_seconds: int = Field(alias="windowSeconds", description="Rolling window duration in seconds")
    max_calls_per_window: int = Field(alias="maxCallsPerWindow", description="Max allowed calls in window")
    approval_threshold: int = Field(alias="approvalThreshold", description="Amount requiring human owner co-signature")
    require_verified_payee: bool = Field(default=False, alias="requireVerifiedPayee")
    allowed_payees: List[str] = Field(default_factory=list, alias="allowedPayees")
    allowed_tokens: List[str] = Field(default_factory=list, alias="allowedTokens")
