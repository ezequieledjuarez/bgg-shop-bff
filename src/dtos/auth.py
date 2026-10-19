from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AuthRequest:
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Any) -> "AuthRequest":
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return cls(payload)


@dataclass(frozen=True)
class UserDto:
    id: str
    email: str
    first_name: str
    last_name: str
    is_active: bool

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UserDto":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionDto:
    access_token: str | None
    refresh_token: str | None
    csrf_token: str | None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SessionDto":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthResponse:
    user: UserDto
    session: SessionDto | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AuthResponse":
        session = value.get("session")
        return cls(
            user=UserDto.from_dict(value["user"]),
            session=SessionDto.from_dict(session) if session else None,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {"user": self.user.to_dict()}
        if self.session is not None:
            result["session"] = self.session.to_dict()
        return result
