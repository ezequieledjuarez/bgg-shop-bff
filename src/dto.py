from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthRequest:
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return cls(payload)


@dataclass(frozen=True)
class ProductQuery:
    page: Any
    page_size: Any
    search: Any
    year_published: Any
    min_players: Any
    max_players: Any
    category_id: Any
    price_min: Any
    price_max: Any

    @classmethod
    def from_request_args(cls, args):
        return cls(
            page=args.get("page", 1),
            page_size=args.get("page_size", 20),
            search=args.get("search"),
            year_published=args.get("year_published"),
            min_players=args.get("min_players"),
            max_players=args.get("max_players"),
            category_id=args.get("category_id"),
            price_min=args.get("price_min"),
            price_max=args.get("price_max"),
        )

    def as_service_kwargs(self):
        return {
            "page": self.page,
            "page_size": self.page_size,
            "search": self.search,
            "year_published": self.year_published,
            "min_players": self.min_players,
            "max_players": self.max_players,
            "category_id": self.category_id,
            "price_min": self.price_min,
            "price_max": self.price_max,
        }
