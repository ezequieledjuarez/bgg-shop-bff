from dataclasses import dataclass
from typing import Any


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    if set(payload) - {"name", "discount_percent", "active", "product_bgg_id"}:
        raise ValueError("Unknown promotion field")
    if any(value is None for key, value in payload.items() if key != "product_bgg_id"):
        raise ValueError("Promotion fields cannot be null")


def _validate_product_bgg_id(value: Any) -> int | None:
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError("product_bgg_id must be a positive integer or null")
    return value


def _validate_discount(value: Any) -> float:
    if type(value) not in (int, float):
        raise ValueError("discount_percent must be a number")
    try:
        discount = float(value)
    except (OverflowError, ValueError):
        raise ValueError("discount_percent must be a number") from None
    if not 0 < discount <= 50:
        raise ValueError("discount_percent must be greater than 0 and at most 50")
    return discount


@dataclass(frozen=True)
class PromotionCreateDto:
    name: Any
    discount_percent: Any
    active: Any
    product_bgg_id: Any = None
    product_bgg_id_provided: bool = False

    @classmethod
    def from_payload(cls, payload: Any) -> "PromotionCreateDto":
        _validate_payload(payload)
        return cls(
            name=payload.get("name"),
            discount_percent=payload.get("discount_percent"),
            active=payload.get("active"),
            product_bgg_id=payload.get("product_bgg_id"),
            product_bgg_id_provided="product_bgg_id" in payload,
        )

    def validate(self) -> dict[str, Any]:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name is required")
        discount = _validate_discount(self.discount_percent)
        if self.active is not None and type(self.active) is not bool:
            raise ValueError("active must be a boolean")
        active = self.active if self.active is not None else False
        data = {"name": self.name.strip(), "discount_percent": discount, "active": active}
        if self.product_bgg_id_provided:
            data["product_bgg_id"] = _validate_product_bgg_id(self.product_bgg_id)
        return data


@dataclass(frozen=True)
class PromotionUpdateDto:
    name: Any
    discount_percent: Any
    active: Any
    product_bgg_id: Any = None
    product_bgg_id_provided: bool = False

    @classmethod
    def from_payload(cls, payload: Any) -> "PromotionUpdateDto":
        _validate_payload(payload)
        return cls(
            name=payload.get("name"),
            discount_percent=payload.get("discount_percent"),
            active=payload.get("active"),
            product_bgg_id=payload.get("product_bgg_id"),
            product_bgg_id_provided="product_bgg_id" in payload,
        )

    def validate(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.name is not None:
            if not isinstance(self.name, str) or not self.name.strip():
                raise ValueError("name, if provided, must be a non-empty string")
            data["name"] = self.name.strip()
        if self.discount_percent is not None:
            data["discount_percent"] = _validate_discount(self.discount_percent)
        if self.active is not None:
            if type(self.active) is not bool:
                raise ValueError("active must be a boolean")
            data["active"] = self.active
        if self.product_bgg_id_provided:
            data["product_bgg_id"] = _validate_product_bgg_id(self.product_bgg_id)
        if not data:
            raise ValueError("at least one field must be provided")
        return data
