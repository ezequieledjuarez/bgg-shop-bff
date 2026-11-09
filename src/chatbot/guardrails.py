import re
import unicodedata


MAX_MESSAGE_LENGTH = 2000

_SHOP_TERMS = re.compile(
    r"\b(store|shop|shipping|deliver(y|ies)|returns?|refunds?|"
    r"payment methods|store hours|opening hours|price|products?|games?|"
    r"board games?|stock|availability|warranty|contact|faq|policy|policies|"
    r"tienda|envios?|entregas?|devoluciones?|reembolsos?|medios de pago|"
    r"horarios?|precios?|productos?|juegos?|disponibilidad|garantia|"
    r"contacto|politicas?|pago|pagos|comprar)\b",
    re.IGNORECASE,
)
_PROTECTED_TERMS = re.compile(
    r"\b(my|i am|i['’]m|i live|we live|my family|my child|my friend|"
    r"your order|order status|order number|order id|"
    r"order tracking|order confirmation|tracking|track my|account details|"
    r"password|username|profile|credit card|card number|social security|ssn|"
    r"passport|driver'?s license|paid|bought|purchased|payment status|"
    r"refund status|invoice for my|purchase status|"
    r"me cobraron|mi|mis|yo|soy|vivo|vivimos|familia|"
    r"estado del pedido|numero de pedido|id del pedido|seguimiento|"
    r"confirmacion del pedido|cuenta|contrasena|usuario|perfil|"
    r"tarjeta de credito|numero de tarjeta|dni|pasaporte|documento de identidad|"
    r"licencia de conducir|pague|pagado|compre|comprado|"
    r"estado del pago|estado del reembolso|estado de la compra|"
    r"factura|direccion|domicilio)\b|"
    r"\b(?:order|pedido)\s+[#A-Z0-9-]{6,}\b",
    re.IGNORECASE,
)
_PERSONAL_HEALTH = re.compile(
    r"\b(?:i have|i was diagnosed with|i(?:['’]ve| have) been diagnosed with|"
    r"i suffer from|tengo|padezco|sufro de|me diagnosticaron)\s+"
    r"(?:(?:type|tipo)\s+[12]\s+)?(?:diabetes|asthma|asma)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_NUMBER = re.compile(r"(?<!\w)\+?\d[\d .()\-]{7,}\d(?!\w)")
_STREET_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Z0-9.'-]+\s+(street|st|avenue|ave|road|rd|"
    r"boulevard|blvd|lane|ln|drive|dr)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_TERMS = re.compile(
    r"\b(joke|weather|recipe|politics|poem|riddle|"
    r"chiste|clima|receta|politica|poema|adivinanza)\b",
    re.IGNORECASE,
)
_UNCLEAR_PATTERNS = (
    re.compile(r"\btell me about it\b", re.IGNORECASE),
    re.compile(r"\b(what about|more about)\s+(it|that|this)\b", re.IGNORECASE),
    re.compile(r"\b(and then|what next)\b", re.IGNORECASE),
    re.compile(r"\b(?:contame|cuentame|decime|dime|hablame)\s+(?:mas\s+)?sobre\s+(?:eso|esto)\b"),
    re.compile(r"\b(?:que hay de|mas sobre|y despues|que sigue)\b"),
)
_SPANISH_GREETING = re.compile(
    r"^[\s¡!¿?.,;:]*"
    r"(?:"
    r"(?:hola(?:[\s,;:!¡¿?]+(?:buenos\s+dias|buenas\s+(?:tardes|noches)))?)"
    r"|buenos\s+dias|buenas\s+(?:tardes|noches)"
    r")"
    r"[\s¡!¿?.,;:]*$",
    re.IGNORECASE,
)
_ENGLISH_GREETING = re.compile(
    r"^[\s¡!¿?.,;:]*"
    r"(?:"
    r"(?:hi|hello)(?:[\s,;:!¡¿?]+good\s+(?:morning|afternoon|evening))?"
    r"|good\s+(?:morning|afternoon|evening)"
    r")"
    r"[\s¡!¿?.,;:]*$",
    re.IGNORECASE,
)


def normalized_message(message):
    return "".join(
        character
        for character in unicodedata.normalize("NFD", message.casefold())
        if not unicodedata.combining(character)
    )


def message_language(message):
    text = normalized_message(message)
    if _SPANISH_GREETING.fullmatch(text):
        return "es"
    if _ENGLISH_GREETING.fullmatch(text):
        return "en"
    # English questions can contain Spanish catalog category names.
    if re.match(r"\s*(?:what|which|how|when|where|why|can|could|tell|recommend|suggest)\b", text):
        return "en"
    if "¿" in message or re.search(
        r"\b(?:que|como|cuando|donde|tienda|pago|juegos?|jugadores?|"
        r"recom(?:end|iend)\w*|sug\w*|contame|cuentame|decime|dime|hablame|"
        r"chiste|clima|receta|politica|poema|adivinanza|"
        r"envios?|devoluciones?|mi|mis|contrasena|cuenta|"
        r"pedido|compre|pague|tengo|padezco|sufro|diagnosticaron|"
        r"direccion|domicilio|mas sobre|y despues)\b", text
    ):
        return "es"
    return "en"


def validate_message_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"message"}:
        return None
    message = payload.get("message")
    if (
        not isinstance(message, str)
        or not message.strip()
        or len(message) > MAX_MESSAGE_LENGTH
    ):
        return None
    return message


def classify_message(message):
    message = normalized_message(message)
    has_shop_topic = _SHOP_TERMS.search(message) is not None
    has_protected_topic = (
        _PROTECTED_TERMS.search(message) is not None
        or _PERSONAL_HEALTH.search(message) is not None
        or _EMAIL.search(message) is not None
        or _PHONE_NUMBER.search(message) is not None
        or _STREET_ADDRESS.search(message) is not None
    )
    if has_protected_topic:
        return "mixed" if has_shop_topic else "protected"
    if _OUT_OF_SCOPE_TERMS.search(message):
        return "out_of_scope"
    if has_shop_topic:
        return "in_scope"
    if _SPANISH_GREETING.fullmatch(message) or _ENGLISH_GREETING.fullmatch(message):
        return "greeting"
    if any(pattern.search(message) for pattern in _UNCLEAR_PATTERNS):
        return "unclear"
    return "out_of_scope"


def reply_for_classification(classification, message=""):
    if message_language(message) == "es":
        return {
            "mixed": (
                "Por favor, envía solo tu pregunta sobre la tienda. No puedo "
                "procesar datos personales, de cuentas, pedidos o transacciones aquí."
            ),
            "protected": (
                "No puedo ayudar con solicitudes personales de cuentas o pedidos aquí. "
                "Usa el canal autenticado de soporte de cuentas o pedidos de la tienda."
            ),
            "out_of_scope": (
                "Puedo ayudar con preguntas sobre la tienda, sus productos y sus "
                "políticas, pero no con esa solicitud."
            ),
            "unclear": (
                "¿Podrías aclarar qué quieres saber sobre la tienda o sus productos? "
                "Por favor, haz una pregunta relacionada con la tienda."
            ),
            "greeting": (
                "Hola, soy Meeple, tu asistente. ¿En qué puedo ayudarte?"
            ),
            "fallback": (
                "No puedo responder con confianza porque la información aprobada "
                "de la tienda no está disponible ahora. Contacta al soporte de la tienda."
            ),
        }[classification]
    replies = {
        "mixed": (
            "Please resubmit only your shop-related question. I can’t process "
            "personal, account, order, or transactional details here."
        ),
        "protected": (
            "I can’t help with personal account or order requests here. Please "
            "use the store’s authenticated account or order support flow."
        ),
        "out_of_scope": (
            "I can help with questions about the store, its products, and its "
            "policies, but not that request."
        ),
        "unclear": (
            "Could you clarify what you’d like to know about the store or its "
            "products? Please ask a store-related question."
        ),
        "greeting": "Hello, I'm Meeple, your assistant. How can I help?",
        "fallback": (
            "I can’t answer with confidence because approved store information "
            "is unavailable right now. Please contact store support."
        ),
    }
    return replies[classification]
