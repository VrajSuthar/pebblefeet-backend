LIKE_ESCAPE = "\\"


def contains_pattern(term: str) -> str:
    """ILIKE pattern matching `term` anywhere, with % and _ taken literally.
    Use together with escape=LIKE_ESCAPE."""
    escaped = (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    )
    return f"%{escaped}%"
