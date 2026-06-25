import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedISBN:
    isbn_13: str | None
    isbn_10: str | None


def _clean(raw: str) -> str:
    return re.sub(r"[^0-9Xx]", "", raw.strip()).upper()


def _isbn10_to_isbn13(isbn_10: str) -> str:
    core = f"978{isbn_10[:9]}"
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    check = (10 - (total % 10)) % 10
    return f"{core}{check}"


def _isbn13_to_isbn10(isbn_13: str) -> str | None:
    if not isbn_13.startswith("978"):
        return None
    core = isbn_13[3:12]
    total = sum((10 - i) * int(d) for i, d in enumerate(core))
    check = (11 - (total % 11)) % 11
    if check == 10:
        check_char = "X"
    else:
        check_char = str(check)
    return f"{core}{check_char}"


def normalize_isbn(raw: str | None) -> NormalizedISBN | None:
    if not raw:
        return None

    cleaned = _clean(raw)
    if not cleaned:
        return None

    if len(cleaned) == 13 and cleaned.isdigit():
        isbn_13 = cleaned
        isbn_10 = _isbn13_to_isbn10(isbn_13)
        return NormalizedISBN(isbn_13=isbn_13, isbn_10=isbn_10)

    if len(cleaned) == 10:
        isbn_10 = cleaned
        isbn_13 = _isbn10_to_isbn13(isbn_10)
        return NormalizedISBN(isbn_13=isbn_13, isbn_10=isbn_10)

    return None


def _validate_isbn10_checksum(isbn_10: str) -> bool:
    if len(isbn_10) != 10:
        return False
    total = 0
    for i, char in enumerate(isbn_10[:9]):
        if not char.isdigit():
            return False
        total += (10 - i) * int(char)
    check_char = isbn_10[9]
    if check_char == "X":
        total += 10
    elif check_char.isdigit():
        total += int(check_char)
    else:
        return False
    return total % 11 == 0


def _validate_isbn13_checksum(isbn_13: str) -> bool:
    if len(isbn_13) != 13 or not isbn_13.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn_13))
    return total % 10 == 0


def validate_isbn_checksum(
    isbn_13: str | None = None,
    isbn_10: str | None = None,
) -> list[str]:
    """Accept-and-warn: return warning strings for invalid checksums."""
    warnings: list[str] = []

    if isbn_13:
        if len(isbn_13) != 13 or not isbn_13.isdigit():
            warnings.append(f"ISBN-13 '{isbn_13}' has invalid format.")
        elif not _validate_isbn13_checksum(isbn_13):
            warnings.append(f"ISBN-13 '{isbn_13}' has an invalid checksum.")

    if isbn_10:
        if len(isbn_10) != 10:
            warnings.append(f"ISBN-10 '{isbn_10}' has invalid format.")
        elif not _validate_isbn10_checksum(isbn_10.upper()):
            warnings.append(f"ISBN-10 '{isbn_10}' has an invalid checksum.")

    return warnings


def normalize_and_validate(
    raw: str | None = None,
    isbn_13: str | None = None,
    isbn_10: str | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """Normalize ISBN fields and collect checksum warnings."""
    warnings: list[str] = []

    if raw:
        normalized = normalize_isbn(raw)
        if normalized:
            return normalized.isbn_13, normalized.isbn_10, validate_isbn_checksum(
                normalized.isbn_13, normalized.isbn_10
            )
        warnings.append(f"ISBN '{raw}' could not be normalized.")
        return None, None, warnings

    final_13 = isbn_13
    final_10 = isbn_10

    if isbn_13:
        cleaned = _clean(isbn_13)
        if len(cleaned) == 13 and cleaned.isdigit():
            final_13 = cleaned
            if not final_10:
                final_10 = _isbn13_to_isbn10(cleaned)
        else:
            warnings.append(f"ISBN-13 '{isbn_13}' has invalid format.")

    if isbn_10 and not final_10:
        cleaned = _clean(isbn_10)
        if len(cleaned) == 10:
            final_10 = cleaned
            if not final_13:
                final_13 = _isbn10_to_isbn13(cleaned)
        else:
            warnings.append(f"ISBN-10 '{isbn_10}' has invalid format.")

    warnings.extend(validate_isbn_checksum(final_13, final_10))
    return final_13, final_10, warnings
