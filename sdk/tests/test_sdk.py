import pytest
from eth_account import Account
from web3 import Web3

from kakoro_sdk.constants import AEVUM_CHAIN_ID
from kakoro_sdk.types import PaymentIntent, PaymentRequirements, PaymentProof
from kakoro_sdk.signer import build_eip712_payload, sign_payment_intent
from kakoro_sdk.ssrf import validate_url, SSRFSecurityError


def test_payment_requirements_parsing():
    raw_req = {
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:44005",
        "asset": "0x456569838f1d43009A91ebA4263147Afd7233483",
        "payTo": "0x1111111111111111111111111111111111111111",
        "amount": 1000000,
        "invoiceId": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "maxTimeoutSeconds": 300,
    }
    req = PaymentRequirements(**raw_req)
    assert req.x402_version == 2
    assert req.amount == 1000000
    assert req.pay_to == "0x1111111111111111111111111111111111111111"


def test_eip712_signing():
    private_key = "0x" + "a" * 64
    account = Account.from_key(private_key)
    verifying_contract = "0x2222222222222222222222222222222222222222"

    intent = PaymentIntent(
        token="0x456569838f1d43009A91ebA4263147Afd7233483",
        payee="0x1111111111111111111111111111111111111111",
        amount=5000000,
        ref="0x" + "b" * 64,
        deadline=1800000000,
        nonce=0,
    )

    sig = sign_payment_intent(
        verifying_contract=verifying_contract,
        intent=intent,
        private_key=private_key,
        chain_id=AEVUM_CHAIN_ID,
    )
    assert sig.startswith("0x")
    assert len(sig) == 132  # 65 bytes in hex + 0x


def test_ssrf_blocks_private_ips():
    # Loopback
    with pytest.raises(SSRFSecurityError):
        validate_url("http://127.0.0.1:8000/api", allow_http=True)

    with pytest.raises(SSRFSecurityError):
        validate_url("http://localhost:8000/api", allow_http=True)

    # AWS / Cloud metadata
    with pytest.raises(SSRFSecurityError):
        validate_url("http://169.254.169.254/latest/meta-data/", allow_http=True)

    # RFC1918 Private
    with pytest.raises(SSRFSecurityError):
        validate_url("http://10.0.0.1/api", allow_http=True)

    # Insecure scheme
    with pytest.raises(SSRFSecurityError):
        validate_url("file:///etc/passwd", allow_http=True)


def test_ssrf_allows_loopback_when_flagged():
    url = "http://127.0.0.1:8000/api/weather"
    validated = validate_url(url, allow_http=True, allow_loopback=True)
    assert validated == url
