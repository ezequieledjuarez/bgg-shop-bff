from dataclasses import asdict, dataclass
from typing import Any

GRAPHQL_INT_MAX = 2**31 - 1


@dataclass(frozen=True)
class CartItemRequestDto:
    bgg_id: int | None
    quantity: int

    @classmethod
    def from_payload(cls, payload: Any, include_bgg_id=True) -> "CartItemRequestDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        allowed_fields = {"quantity", "bgg_id"} if include_bgg_id else {"quantity"}
        if not payload.keys() <= allowed_fields:
            raise ValueError("Request contains an unsupported field")
        bgg_id = payload.get("bgg_id") if include_bgg_id else None
        quantity = payload.get("quantity")
        if include_bgg_id and (
            not isinstance(bgg_id, int) or isinstance(bgg_id, bool) or not 1 <= bgg_id <= GRAPHQL_INT_MAX
        ):
            raise ValueError("bgg_id must be a positive integer")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= GRAPHQL_INT_MAX:
            raise ValueError("quantity must be a positive integer")
        return cls(bgg_id=bgg_id, quantity=quantity)


@dataclass(frozen=True)
class CartResponseDto:
    lines: list[dict[str, Any]]
    total: float
    warnings: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CartResponseDto":
        return cls(lines=value["lines"], total=value["total"], warnings=value["warnings"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
