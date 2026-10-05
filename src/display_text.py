"""ASCII fallback for text literals in Nextion/TJC display commands.

Only display strings are transliterated. Command names, component identifiers,
numeric values and already-ASCII commands are never rewritten.
"""
import re
import unicodedata


_TEXT_LITERAL = re.compile(r'"((?:\\.|[^"\\])*)"')
_REPLACEMENTS = str.maketrans({
    "°": " deg", "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE",
    "ß": "ss", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L",
    "’": "'", "‘": "'", "“": "'", "”": "'", "«": "'", "»": "'",
    "–": "-", "—": "-", "−": "-", "…": "...",
    "→": "->", "←": "<-", "↑": "^", "↓": "v", "×": "x",
})


class DisplayEncodingError(ValueError):
    """A command contains non-ASCII syntax outside display text literals."""


def _ascii_text(value):
    value = value.replace("°C", " C").replace("°F", " F")
    result = []
    for char in value:
        if char.isascii():
            # Preserve existing ASCII and escape sequences byte-for-byte.
            result.append(char)
            continue
        if char.isspace():
            result.append(" ")
            continue
        if unicodedata.category(char) in ("Mn", "Me", "Cf"):
            continue
        replacement = char.translate(_REPLACEMENTS)
        if replacement == char:
            decomposed = unicodedata.normalize("NFKD", char)
            replacement = "".join(
                c for c in decomposed if not unicodedata.combining(c)
            )
            if not replacement.isascii():
                replacement = "?"
        # Normalization must not introduce a quote, backslash or control byte
        # into an existing quoted command (e.g. full-width quotation marks).
        replacement = "".join(
            "?" if c in ('"', "\\") or ord(c) < 32 or ord(c) == 127 else c
            for c in replacement
        )
        result.append(replacement)
    return "".join(result)


def ascii_display_command(command):
    """Return a serializable command, or reject non-ASCII command syntax."""
    if command.isascii():
        return command
    converted = _TEXT_LITERAL.sub(
        lambda match: '"' + _ascii_text(match.group(1)) + '"', command
    )
    if not converted.isascii():
        raise DisplayEncodingError(
            "non-ASCII outside a quoted display string; command not sent"
        )
    return converted
