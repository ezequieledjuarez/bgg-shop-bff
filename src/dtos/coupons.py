from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CouponApplyDto:
    cart_id: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "CouponApplyDto":
        if payload is None:
            # allow empty body
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(cart_id=payload.get("cart_id"))

    def validate(self) -> dict[str, Any]:
        if self.cart_id in (None, ""):
            # guest previews allowed with no cart_id
            return {}
        try:
            # accept string UUIDs or integers
            return {"cart_id": str(self.cart_id)}
        except (TypeError, ValueError):
            raise ValueError("cart_id must be a string or UUID")
