import re

_DASH_RE = re.compile(r"\s*[\u2014\u2013\u2015]+\s*")


def strip_dashes(text: str) -> str:
    return _DASH_RE.sub(", ", text or "")


def clean_text(value: object) -> str:
    return strip_dashes(str(value or "")).strip()
