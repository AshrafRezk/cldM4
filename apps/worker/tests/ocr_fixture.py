"""Stand-in for Apple Vision. The golden string is the invoice line."""

GOLDEN = "INVOICE 42"


def recognize(data: bytes) -> str:
    if not data:
        raise ValueError("empty image")
    return GOLDEN
