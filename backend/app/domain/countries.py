"""Canonical country names stored on every accepted order."""

CANONICAL_COUNTRIES: tuple[str, ...] = (
    "España",
    "Francia",
    "Alemania",
    "Italia",
    "Portugal",
    "México",
    "Argentina",
    "Chile",
    "Colombia",
    "Estados Unidos",
)

# The stored names use Spanish spelling, including accents. The keys are folded.
_ALIASES: dict[str, str] = {
    "espana": "España",
    "spain": "España",
    "es": "España",
    "francia": "Francia",
    "france": "Francia",
    "alemania": "Alemania",
    "germany": "Alemania",
    "italia": "Italia",
    "italy": "Italia",
    "portugal": "Portugal",
    "mexico": "México",
    "argentina": "Argentina",
    "chile": "Chile",
    "colombia": "Colombia",
    "estados unidos": "Estados Unidos",
    "united states": "Estados Unidos",
    "usa": "Estados Unidos",
}


def _fold(value: str) -> str:
    """Lowercase and strip accents so Spain and Espana share one key."""
    folded = value.strip().lower()
    return (
        folded.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def canonical_country(value: str) -> str | None:
    """Return the stored country name, or None when the text is not in the table."""
    return _ALIASES.get(_fold(value))
