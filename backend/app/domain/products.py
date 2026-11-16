"""Product names stored on accepted orders, and foreign words that mean them."""

# Keys are folded. The value is the sample catalog spelling.
_ALIASES: dict[str, str] = {
    "teclado": "Teclado",
    "teclados": "Teclado",
    "keyboard": "Teclado",
    "keyboards": "Teclado",
    "clavier": "Teclado",
    "claviers": "Teclado",
    "tastatur": "Teclado",
    "monitor": "Monitor",
    "monitors": "Monitor",
    "moniteur": "Monitor",
    "monitores": "Monitor",
    "screen": "Monitor",
    "screens": "Monitor",
    "silla": "Silla",
    "sillas": "Silla",
    "chair": "Silla",
    "chairs": "Silla",
    "chaise": "Silla",
    "chaises": "Silla",
    "stuhl": "Silla",
    "cadeira": "Silla",
    "cable": "Cable",
    "cables": "Cable",
    "cabo": "Cable",
    "kabel": "Cable",
    "lampara": "Lampara",
    "lamparas": "Lampara",
    "lamp": "Lampara",
    "lamps": "Lampara",
    "lampe": "Lampara",
    "lampes": "Lampara",
    "lampada": "Lampara",
}


def fold_product(value: str) -> str:
    """Lowercase and strip accents so Lampara and Lámpara share one key."""
    folded = value.strip().lower()
    return (
        folded.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def canonical_product(value: str, stored: dict[str, str]) -> str | None:
    """Return the stored spelling for a product word, or None when it is unknown.

    stored maps a folded name to the spelling loaded from the file.
    A word already stored wins over the catalog alias.
    """
    folded = fold_product(value)
    if folded in stored:
        return stored[folded]
    target = _ALIASES.get(folded)
    if target is None:
        return None
    return stored.get(fold_product(target))
