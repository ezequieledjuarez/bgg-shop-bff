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
    quantity: int
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


@dataclass(frozen=True)
class ProductDetailDto:
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
    quantity: int
    publisher: str
    image_url: str
    review_summary: dict[str, Any]
    approved_reviews: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductDetailDto":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CreateReviewRequestDto:
    rating: Any
    body: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "CreateReviewRequestDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(rating=payload.get("rating"), body=payload.get("body"))


@dataclass(frozen=True)
class CreateReviewResponseDto:
    created: bool
    status: str
    created_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CreateReviewResponseDto":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdminCreateProductDto:
    name: Any
    price: Any
    quantity: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdminCreateProductDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(name=payload.get("name"), price=payload.get("price"), quantity=payload.get("quantity"))

    def validate(self) -> dict[str, Any]:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name is required")
        try:
            price = float(self.price)
        except (TypeError, ValueError):
            raise ValueError("price must be a number")
        if price < 0:
            raise ValueError("price must be greater than or equal to 0")
        try:
            quantity = int(self.quantity)
        except (TypeError, ValueError):
            raise ValueError("quantity must be an integer")
        if quantity < 0:
            raise ValueError("quantity must be greater than or equal to 0")
        return {"name": self.name.strip(), "price": price, "quantity": quantity}


@dataclass(frozen=True)
class AdminUpdateProductDto:
    name: Any
    price: Any
    quantity: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdminUpdateProductDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(name=payload.get("name"), price=payload.get("price"), quantity=payload.get("quantity"))

    def validate(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.name is not None:
            if not isinstance(self.name, str) or not self.name.strip():
                raise ValueError("name, if provided, must be a non-empty string")
            data["name"] = self.name.strip()
        if self.price is not None:
            try:
                price = float(self.price)
            except (TypeError, ValueError):
                raise ValueError("price must be a number")
            if price < 0:
                raise ValueError("price must be greater than or equal to 0")
            data["price"] = price
        if self.quantity is not None:
            try:
                quantity = int(self.quantity)
            except (TypeError, ValueError):
                raise ValueError("quantity must be an integer")
            if quantity < 0:
                raise ValueError("quantity must be greater than or equal to 0")
            data["quantity"] = quantity
        if not data:
            raise ValueError("at least one field must be provided")
        return data


@dataclass(frozen=True)
class AdjustStockDto:
    new_stock: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdjustStockDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(new_stock=payload.get("new_stock"))

    def validate(self) -> int:
        try:
            new_stock_int = int(self.new_stock)
        except (TypeError, ValueError):
            raise ValueError("new_stock must be an integer")
        if new_stock_int < 0:
            raise ValueError("new_stock must be greater than or equal to 0")
        return new_stock_int
