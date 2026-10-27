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
    bgg_id: Any
    name: Any
    price: Any
    price_amount: Any
    quantity: Any
    release_year: Any
    min_players: Any
    max_players: Any
    playing_time_minutes: Any
    min_age: Any
    max_age: Any
    weight: Any
    category: Any
    publisher: Any
    image_file_name: Any
    image_url: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdminCreateProductDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(
            bgg_id=payload.get("bggId") or payload.get("bgg_id"),
            name=payload.get("name"),
            price=payload.get("price"),
            price_amount=payload.get("priceAmount") or payload.get("price_amount") or payload.get("price"),
            quantity=payload.get("quantity"),
            release_year=payload.get("releaseYear") or payload.get("release_year"),
            min_players=payload.get("minPlayers") or payload.get("min_players"),
            max_players=payload.get("maxPlayers") or payload.get("max_players"),
            playing_time_minutes=payload.get("playingTimeMinutes") or payload.get("playing_time_minutes"),
            min_age=payload.get("minAge") or payload.get("min_age"),
            max_age=payload.get("maxAge") or payload.get("max_age"),
            weight=payload.get("weight"),
            category=payload.get("category"),
            publisher=payload.get("publisher"),
            image_file_name=payload.get("imageFileName") or payload.get("image_file_name"),
            image_url=payload.get("imageUrl") or payload.get("image_url"),
        )

    def _to_camelcase_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        # Map snake_case keys to camelCase expected by upstream GraphQL
        mapping = {
            'bgg_id': 'bggId',
            'release_year': 'releaseYear',
            'min_players': 'minPlayers',
            'max_players': 'maxPlayers',
            'playing_time_minutes': 'playingTimeMinutes',
            'min_age': 'minAge',
            'max_age': 'maxAge',
            'price_amount': 'price',
            'image_file_name': 'imageFileName',
            'image_url': 'imageUrl',
        }
        out = {}
        for k, v in data.items():
            if v is None:
                continue
            if k in mapping:
                out[mapping[k]] = v
            else:
                out[k] = v
        return out

    def validate(self) -> dict[str, Any]:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name is required")
        # price_amount preferred, fall back to price
        try:
            price = float(self.price_amount)
        except (TypeError, ValueError):
            try:
                price = float(self.price)
            except (TypeError, ValueError):
                raise ValueError("priceAmount (or price) must be a number")
        if price < 0:
            raise ValueError("price must be greater than or equal to 0")
        try:
            quantity = int(self.quantity)
        except (TypeError, ValueError):
            raise ValueError("quantity must be an integer")
        if quantity < 0:
            raise ValueError("quantity must be greater than or equal to 0")

        # optional integer fields
        def _opt_int(v, name):
            if v in (None, ''):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be an integer")

        def _opt_float(v, name):
            if v in (None, ''):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number")

        payload = {
            'bgg_id': (int(self.bgg_id) if self.bgg_id not in (None, '') else None),
            'name': self.name.strip(),
            'price': price,
            'quantity': quantity,
            'release_year': _opt_int(self.release_year, 'release_year'),
            'min_players': _opt_int(self.min_players, 'min_players'),
            'max_players': _opt_int(self.max_players, 'max_players'),
            'playing_time_minutes': _opt_int(self.playing_time_minutes, 'playing_time_minutes'),
            'min_age': _opt_int(self.min_age, 'min_age'),
            'max_age': _opt_int(self.max_age, 'max_age'),
            'weight': _opt_float(self.weight, 'weight'),
            'category': self.category,
            'publisher': (self.publisher.strip() if isinstance(self.publisher, str) and self.publisher.strip() else None),
            'image_file_name': (self.image_file_name if isinstance(self.image_file_name, str) and self.image_file_name.strip() else None),
            'image_url': (self.image_url if isinstance(self.image_url, str) and self.image_url.strip() else None),
        }

        # normalize category: accept comma-separated string or list
        cat = payload.get('category')
        if isinstance(cat, str):
            payload['category'] = [c.strip() for c in cat.split(',') if c.strip()]
        elif cat is None:
            payload['category'] = []
        elif isinstance(cat, list):
            payload['category'] = [str(c) for c in cat]
        else:
            raise ValueError('category must be a list or comma-separated string')

        # Build camelCase dict for upstream
        # include bggId if present
        camel = self._to_camelcase_dict(payload)
        return camel


@dataclass(frozen=True)
class AdminUpdateProductDto:
    bgg_id: Any
    name: Any
    price: Any
    price_amount: Any
    quantity: Any
    release_year: Any
    min_players: Any
    max_players: Any
    playing_time_minutes: Any
    min_age: Any
    max_age: Any
    weight: Any
    category: Any
    publisher: Any
    image_file_name: Any
    image_url: Any

    @classmethod
    def from_payload(cls, payload: Any) -> "AdminUpdateProductDto":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return cls(
            bgg_id=payload.get("bggId") or payload.get("bgg_id"),
            name=payload.get("name"),
            price=payload.get("price"),
            price_amount=payload.get("priceAmount") or payload.get("price_amount") or payload.get("price"),
            quantity=payload.get("quantity"),
            release_year=payload.get("releaseYear") or payload.get("release_year"),
            min_players=payload.get("minPlayers") or payload.get("min_players"),
            max_players=payload.get("maxPlayers") or payload.get("max_players"),
            playing_time_minutes=payload.get("playingTimeMinutes") or payload.get("playing_time_minutes"),
            min_age=payload.get("minAge") or payload.get("min_age"),
            max_age=payload.get("maxAge") or payload.get("max_age"),
            weight=payload.get("weight"),
            category=payload.get("category"),
            publisher=payload.get("publisher"),
            image_file_name=payload.get("imageFileName") or payload.get("image_file_name"),
            image_url=payload.get("imageUrl") or payload.get("image_url"),
        )

    def _to_camelcase_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            'bgg_id': 'bggId',
            'release_year': 'releaseYear',
            'min_players': 'minPlayers',
            'max_players': 'maxPlayers',
            'playing_time_minutes': 'playingTimeMinutes',
            'min_age': 'minAge',
            'max_age': 'maxAge',
            'price_amount': 'price',
            'image_file_name': 'imageFileName',
            'image_url': 'imageUrl',
        }
        out = {}
        for k, v in data.items():
            if v is None:
                continue
            if k in mapping:
                out[mapping[k]] = v
            else:
                out[k] = v
        return out

    def validate(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.name is not None:
            if not isinstance(self.name, str) or not self.name.strip():
                raise ValueError("name, if provided, must be a non-empty string")
            data["name"] = self.name.strip()
        # price handling
        if self.price_amount is not None or self.price is not None:
            try:
                price = float(self.price_amount) if self.price_amount is not None else float(self.price)
            except (TypeError, ValueError):
                raise ValueError("priceAmount (or price) must be a number")
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

        def _opt_int(v, name):
            if v in (None, ''):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be an integer")

        def _opt_float(v, name):
            if v in (None, ''):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number")

        # optional fields
        extra = {
            'bgg_id': (int(self.bgg_id) if self.bgg_id not in (None, '') else None),
            'release_year': _opt_int(self.release_year, 'release_year'),
            'min_players': _opt_int(self.min_players, 'min_players'),
            'max_players': _opt_int(self.max_players, 'max_players'),
            'playing_time_minutes': _opt_int(self.playing_time_minutes, 'playing_time_minutes'),
            'min_age': _opt_int(self.min_age, 'min_age'),
            'max_age': _opt_int(self.max_age, 'max_age'),
            'weight': _opt_float(self.weight, 'weight'),
            'category': self.category,
            'publisher': (self.publisher.strip() if isinstance(self.publisher, str) and self.publisher.strip() else None),
            'image_file_name': (self.image_file_name if isinstance(self.image_file_name, str) and self.image_file_name.strip() else None),
            'image_url': (self.image_url if isinstance(self.image_url, str) and self.image_url.strip() else None),
        }

        # normalize category
        cat = extra.get('category')
        if isinstance(cat, str):
            extra['category'] = [c.strip() for c in cat.split(',') if c.strip()]
        elif cat is None:
            extra['category'] = None
        elif isinstance(cat, list):
            extra['category'] = [str(c) for c in cat]
        else:
            raise ValueError('category must be a list or comma-separated string')

        # merge extra fields into data using camelCase mapping
        camel = self._to_camelcase_dict(extra)
        data.update(camel)

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
