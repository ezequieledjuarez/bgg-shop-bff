from dataclasses import dataclass
from datetime import datetime
import math
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


_COUPON_CREATE_FIELDS = {
    "code", "discount_percent", "remaining", "active", "starts_at", "ends_at",
}
_COUPON_UPDATE_FIELDS = {
    "discount_percent", "remaining", "active", "starts_at", "ends_at",
}
_MAX_REMAINING = 9223372036854775807


def _validate_coupon_dates(payload: dict[str, Any]) -> None:
    parsed: dict[str, datetime | None] = {}
    for field in ("starts_at", "ends_at"):
        if field not in payload or payload[field] is None:
            parsed[field] = None
            continue
        value = payload[field]
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a timezone-aware date-time or null")
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{field} must be a timezone-aware date-time or null") from None
        if date.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        parsed[field] = date
    start = parsed.get("starts_at")
    end = parsed.get("ends_at")
    if start is not None and end is not None and start >= end:
        raise ValueError("starts_at must be earlier than ends_at")


def _validate_coupon_payload(
    payload: Any, allowed: set[str], required: set[str]
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    if set(payload) - allowed:
        raise ValueError("Unknown coupon field")
    if required - set(payload):
        raise ValueError("Required coupon fields are missing")

    result = dict(payload)
    if "code" in result:
        code = result["code"]
        if not isinstance(code, str) or not code or len(code) > 64:
            raise ValueError("code must contain 1 to 64 characters")
    if "discount_percent" in result:
        discount = result["discount_percent"]
        if type(discount) not in (int, float):
            raise ValueError("discount_percent must be a finite number from 0 to 50")
        try:
            numeric_discount = float(discount)
        except (OverflowError, ValueError):
            raise ValueError("discount_percent must be a finite number from 0 to 50") from None
        if not math.isfinite(numeric_discount) or not 0 <= numeric_discount <= 50:
            raise ValueError("discount_percent must be from 0 to 50")
        result["discount_percent"] = numeric_discount
    if "remaining" in result:
        remaining = result["remaining"]
        if type(remaining) is not int or not 0 <= remaining <= _MAX_REMAINING:
            raise ValueError("remaining must be a non-negative integer")
    if "active" in result and type(result["active"]) is not bool:
        raise ValueError("active must be a boolean")
    for field in set(result) - {"starts_at", "ends_at"}:
        if result[field] is None:
            raise ValueError(f"{field} cannot be null")
    _validate_coupon_dates(result)
    return result


@dataclass(frozen=True)
class AdminCouponCreateDto:
    payload: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdminCouponCreateDto":
        return cls(payload=payload)

    def validate(self) -> dict[str, Any]:
        return _validate_coupon_payload(
            self.payload,
            _COUPON_CREATE_FIELDS,
            {"code", "discount_percent", "remaining", "active"},
        )


@dataclass(frozen=True)
class AdminCouponUpdateDto:
    payload: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdminCouponUpdateDto":
        return cls(payload=payload)

    def validate(self) -> dict[str, Any]:
        validated = _validate_coupon_payload(
            self.payload, _COUPON_UPDATE_FIELDS, set()
        )
        if not validated:
            raise ValueError("At least one coupon field must be provided")
        return validated
