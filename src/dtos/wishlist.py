from dataclasses import dataclass
from typing import Any


GRAPHQL_INT_MAX = 2**31 - 1


@dataclass(frozen=True)
class WishlistAddRequestDto:
    bgg_id: int

    @classmethod
    def from_payload(cls, payload: Any) -> "WishlistAddRequestDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        if set(payload) != {"bgg_id"}:
            raise ValueError("Request body must contain only bgg_id")
        bgg_id = payload["bgg_id"]
        if type(bgg_id) is not int or not 1 <= bgg_id <= GRAPHQL_INT_MAX:
            raise ValueError("bgg_id must be a positive integer")
        return cls(bgg_id=bgg_id)
