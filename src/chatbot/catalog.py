import re

from .guardrails import message_language, normalized_message

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}
_NUMBER = rf"(?:\d{{1,3}}|{'|'.join(_NUMBER_WORDS)})"
_RECOMMENDATION_INTENT = re.compile(
    r"\b(?:recommend(?:ation|ations)?|suggest(?:ion|ions)?|"
    r"what\s+(?:product|game|board game)\s+should\s+i\s+(?:buy|choose)|"
    r"which\s+(?:product|game|board game)\s+should\s+i\s+(?:buy|choose)|"
    r"recom(?:end|iend)\w*|sugier\w*|suger\w*|"
    r"que\s+(?:producto|juego)s?\s+(?:deberia\s+)?(?:comprar|elegir))\b",
    re.IGNORECASE,
)
_UNSUPPORTED_PLAYTIME = re.compile(
    r"\b(?:play(?:ing)?\s*time|playtime|duration|"
    r"(?:takes?|lasts?|within|under|over|less than|more than)\s+"
    r"\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?)|"
    r"duracion|tiempo de juego|minutos?|horas?)\b",
    re.IGNORECASE,
)
_PLAYER_RANGE = re.compile(
    rf"\b({_NUMBER})\s*(?:-|to|and|a|y)\s*({_NUMBER})\s+(?:players?|jugadores?)\b",
    re.IGNORECASE,
)
_PLAYER_COUNT = re.compile(
    rf"\b(?:(?:exactly|exactamente)\s+)?({_NUMBER})\s+(?:players?|jugadores?)\b",
    re.IGNORECASE,
)
_PRICE_RANGE = re.compile(
    r"\b(?:between|entre)\s+[$€£]?\s*([\d,]+(?:\.\d+)?)\s*"
    r"(?:and|to|-|y|a)\s*[$€£]?\s*([\d,]+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_PRICE_MAX = re.compile(
    r"\b(?:under|below|less than|up to|at most|no more than|maximum|max|"
    r"menos de|hasta|como maximo|maximo)\s+"
    r"[$€£]?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PRICE_MIN = re.compile(
    r"\b(?:over|above|more than|at least|minimum|min|mas de|al menos|minimo)\s+"
    r"[$€£]?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_EXPLICIT_CATEGORY = re.compile(
    r"\b(?:category|genre)\s*(?:is|:)\s*([^,.!?;]+)",
    re.IGNORECASE,
)
_CATEGORY_BEFORE_FILTER = re.compile(
    r"\bwant\s+([^,.!?;]+?)\s+(?="
    r"(?:for\s+(?:(?:exactly|about|around)\s+)?"
    rf"{_NUMBER}\s+players?|under\b|below\b|less than\b|"
    r"up to\b|at most\b|no more than\b|between\b|over\b|above\b|"
    r"more than\b|at least\b))",
    re.IGNORECASE,
)
_GENERIC_CATEGORIES = {
    "a game",
    "game",
    "a board game",
    "board game",
    "a product",
    "product",
    "something",
}
_SPANISH_CATEGORY = re.compile(
    r"\b(?:juegos?(?: de mesa)?\s+de|categoria\s*(?:es|:))\s*"
    r"([^,.!?;]+?)(?=\s+(?:para|por|menos de|hasta|entre|mas de|al menos)\b|[,.!?;]|$)"
)
_UNSUPPORTED_FILTER = re.compile(
    r"\b(?:idioma|edicion|editorial|edad|anos|dificultad|complejidad|peso)\b"
)
_UNSUPPORTED_AUDIENCE = re.compile(
    r"\b(?:child(?:ren)?|kids?|ages?|age|ninos?|ninas?)\b"
)


def _number(value):
    normalized = value.casefold()
    if normalized in _NUMBER_WORDS:
        return _NUMBER_WORDS[normalized]
    return int(value)


def _price(value):
    return float(value.replace(",", ""))


def _category(message):
    match = _EXPLICIT_CATEGORY.search(message)
    if match is None:
        match = _CATEGORY_BEFORE_FILTER.search(message)
    if match is None:
        match = _SPANISH_CATEGORY.search(normalized_message(message))
        if match is None:
            return None
        category = match.group(1).strip()
        # Core category names remain canonical catalog values, not translated filters.
        if category == "estrategia":
            return "Juegos de Estrategia"
        return category
    category = match.group(1).strip()
    if category.casefold() in _GENERIC_CATEGORIES:
        return None
    return category


def recommendation_request(message):
    """Return supported Core filters, an unsupported-filter clarification, or None."""
    language = message_language(message)
    original_message = message
    message = normalized_message(message)
    if _RECOMMENDATION_INTENT.search(message) is None:
        return None
    if _UNSUPPORTED_AUDIENCE.search(message):
        return {
            "filters": None,
            "clarification": (
                "No puedo filtrar el catálogo por edad o público todavía. "
                "Elige una categoría, cantidad de jugadores o precio."
            ) if language == "es" else (
                "I can't filter the catalog by age or audience yet. Please choose a "
                "category, player count, or price instead."
            ),
        }
    if _UNSUPPORTED_PLAYTIME.search(message) or (
        language == "es" and _UNSUPPORTED_FILTER.search(message)
    ):
        return {
            "filters": None,
            "clarification": (
                "No puedo filtrar el catálogo por esa característica todavía. "
                "Elige una categoría, cantidad de jugadores o precio."
            ) if language == "es" else (
                "I can't filter the catalog by playtime yet. Please choose a "
                "category, player count, or price instead."
            ),
        }

    filters = {}
    player_range = _PLAYER_RANGE.search(message)
    player_count = _PLAYER_COUNT.search(message)
    if player_range:
        min_players, max_players = map(_number, player_range.groups())
        if min_players <= max_players:
            filters.update(min_players=min_players, max_players=max_players)
    elif player_count:
        player_count_value = _number(player_count.group(1))
        filters.update(
            min_players=player_count_value,
            max_players=player_count_value,
        )

    price_range = _PRICE_RANGE.search(message)
    if price_range:
        price_min, price_max = map(_price, price_range.groups())
        if price_min <= price_max:
            filters.update(price_min=price_min, price_max=price_max)
    else:
        price_max = _PRICE_MAX.search(message)
        price_min = _PRICE_MIN.search(message)
        if price_max:
            filters["price_max"] = _price(price_max.group(1))
        if price_min:
            filters["price_min"] = _price(price_min.group(1))

    category = _category(original_message)
    if category:
        filters["category_name"] = category

    return {"filters": filters, "clarification": None}
