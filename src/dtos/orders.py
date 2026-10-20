from dataclasses import dataclass
from typing import Any
import re
import uuid


_ADDRESS_FIELDS = {"recipient", "street", "city", "postal_code", "phone"}
_PAYMENT_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


def order_uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("order_id must be a UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("order_id must be a UUID") from exc


@dataclass(frozen=True)
class CheckoutRequestDto:
    shipping_mode: str
    address: dict[str, str | None] | None

    @classmethod
    def from_payload(cls, payload: Any) -> "CheckoutRequestDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        if not payload.keys() <= {"shipping_mode", "address"}:
            raise ValueError("Request contains an unsupported field")
        shipping_mode = payload.get("shipping_mode")
        if shipping_mode not in ("standard", "pickup"):
            raise ValueError("shipping_mode must be standard or pickup")
        address = payload.get("address")
        if address is not None:
            if not isinstance(address, dict) or not address.keys() <= _ADDRESS_FIELDS:
                raise ValueError("address must be an object with supported fields")
            address = dict(address)
            for name, value in address.items():
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"address.{name} must be a string")
                if isinstance(value, str):
                    address[name] = value.strip()
                    if len(address[name]) > 255:
                        raise ValueError(f"address.{name} must not exceed 255 characters")
        return cls(shipping_mode=shipping_mode, address=address)

    def to_core(self) -> tuple[str, dict[str, str | None] | None]:
        return self.shipping_mode, self.address


@dataclass(frozen=True)
class ConfirmPaymentRequestDto:
    order_id: str
    payment_id: str

    @classmethod
    def from_payload(cls, payload: Any) -> "ConfirmPaymentRequestDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        if payload.keys() != {"order_id", "payment_id"}:
            raise ValueError("Request must contain only order_id and payment_id")
        order_id = order_uuid(payload.get("order_id"))
        payment_id = payload.get("payment_id")
        if isinstance(payment_id, bool) or not isinstance(payment_id, (str, int)):
            raise ValueError("payment_id must contain only safe identifier characters")
        payment_id = str(payment_id).strip()
        if not _PAYMENT_ID.fullmatch(payment_id):
            raise ValueError("payment_id must contain only safe identifier characters and be at most 128 characters")
        return cls(order_id=order_id, payment_id=payment_id)
