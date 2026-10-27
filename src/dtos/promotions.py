from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromotionCreateDto:
    name: Any
    discount_percent: Any
    active: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "PromotionCreateDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(name=payload.get("name"), discount_percent=payload.get("discount_percent"), active=payload.get("active"))

    def validate(self) -> dict[str, Any]:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name is required")
        try:
            discount = float(self.discount_percent)
        except (TypeError, ValueError):
            raise ValueError("discount_percent must be a number")
        if discount <= 0 or discount > 100:
            raise ValueError("discount_percent must be between 0 and 100")
        active = bool(self.active)
        return {"name": self.name.strip(), "discount_percent": discount, "active": active}


@dataclass(frozen=True)
class PromotionUpdateDto:
    name: Any
    discount_percent: Any
    active: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "PromotionUpdateDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(name=payload.get("name"), discount_percent=payload.get("discount_percent"), active=payload.get("active"))

    def validate(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.name is not None:
            if not isinstance(self.name, str) or not self.name.strip():
                raise ValueError("name, if provided, must be a non-empty string")
            data["name"] = self.name.strip()
        if self.discount_percent is not None:
            try:
                discount = float(self.discount_percent)
            except (TypeError, ValueError):
                raise ValueError("discount_percent must be a number")
            if discount <= 0 or discount > 100:
                raise ValueError("discount_percent must be between 0 and 100")
            data["discount_percent"] = discount
        if self.active is not None:
            data["active"] = bool(self.active)
        if not data:
            raise ValueError("at least one field must be provided")
        return data
