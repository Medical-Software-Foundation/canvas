def to_bool(value: str) -> bool:
    if not value:
        return False

    return value.lower().strip() not in ('false', 'f', 'n', 'no', '0', '')
