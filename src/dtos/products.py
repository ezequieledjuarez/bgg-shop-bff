from dataclasses import asdict, dataclass
from typing import Any


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
    def from_request_args(cls, args) -> "ProductQuery":
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

    def as_service_kwargs(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductDto:
    bgg_id: int
    name: str
    release_year: int
    min_players: int
    max_players: int
    playing_time_minutes: int
    min_age: int
    weight: float
    category: list[str]
    price: float
    publisher: str
    image_url: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductDto":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductPageDto:
    items: list[ProductDto | dict[str, Any]]
    page: int
    page_size: int
    total: int
    total_pages: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductPageDto":
        product_fields = set(ProductDto.__dataclass_fields__)
        return cls(
            items=[
                ProductDto.from_dict(item)
                if product_fields.issubset(item)
                else item
                for item in value["items"]
            ],
            page=value["page"],
            page_size=value["page_size"],
            total=value["total"],
            total_pages=value["total_pages"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [
                item.to_dict() if isinstance(item, ProductDto) else item
                for item in self.items
            ],
            "page": self.page,
            "page_size": self.page_size,
            "total": self.total,
            "total_pages": self.total_pages,
        }
