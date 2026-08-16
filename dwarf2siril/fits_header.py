"""Minimal FITS primary-header reader.

Deliberately stdlib-only. We only ever need the primary header keywords the
DWARF 3 writes, so pulling in astropy for this would be a whole dependency for
about forty lines of work.

FITS layout, as much of it as we care about: the file starts with 2880-byte
blocks of 80-character ASCII "cards". Each card is ``KEYWORD = value / comment``.
The header ends at the card ``END``. We stop there and never touch the pixel
data, which is what keeps this fast enough to run over a few hundred 16 MB
frames while the user watches.
"""

from __future__ import annotations

import os
from typing import Any

BLOCK_SIZE = 2880
CARD_SIZE = 80
CARDS_PER_BLOCK = BLOCK_SIZE // CARD_SIZE

# A header this long means we are not reading a FITS file, we are reading
# garbage. Bail rather than walk a multi-gigabyte file 80 bytes at a time.
MAX_BLOCKS = 64


class FitsHeaderError(Exception):
    """Raised when a file cannot be read as a FITS primary header."""


def _parse_value(raw: str) -> Any:
    """Turn the value part of a card into a Python value."""
    raw = raw.strip()
    if not raw:
        return None

    # Strings are single-quoted and pad themselves out with spaces, e.g.
    # ``'TELE    '``. Doubled quotes are the FITS escape for a literal quote.
    if raw.startswith("'"):
        end = 1
        chars: list[str] = []
        while end < len(raw):
            char = raw[end]
            if char == "'":
                if end + 1 < len(raw) and raw[end + 1] == "'":
                    chars.append("'")
                    end += 2
                    continue
                break
            chars.append(char)
            end += 1
        return "".join(chars).strip()

    if raw in ("T", "F"):
        return raw == "T"

    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _split_card(card: str) -> tuple[str, Any] | None:
    keyword = card[:8].strip()
    if not keyword or keyword in ("COMMENT", "HISTORY", "END"):
        return None
    if card[8:10] != "= ":
        return None

    rest = card[10:]

    # Strip the trailing comment, but only a '/' that is outside a quoted
    # string -- filter names and object names are allowed to contain slashes.
    in_string = False
    cut = len(rest)
    index = 0
    while index < len(rest):
        char = rest[index]
        if char == "'":
            if in_string and index + 1 < len(rest) and rest[index + 1] == "'":
                index += 2
                continue
            in_string = not in_string
        elif char == "/" and not in_string:
            cut = index
            break
        index += 1

    return keyword, _parse_value(rest[:cut])


def read_header(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read the primary header of a FITS file into a dict.

    Raises :class:`FitsHeaderError` if the file is not FITS or the header
    never terminates.
    """
    header: dict[str, Any] = {}
    try:
        with open(path, "rb") as handle:
            first = handle.read(BLOCK_SIZE)
            if not first.startswith(b"SIMPLE  ="):
                raise FitsHeaderError(f"not a FITS file (no SIMPLE card): {path}")

            block = first
            for _ in range(MAX_BLOCKS):
                if not block:
                    break
                text = block.decode("ascii", errors="replace")
                for index in range(CARDS_PER_BLOCK):
                    card = text[index * CARD_SIZE : (index + 1) * CARD_SIZE]
                    if card[:3] == "END" and not card[3:].strip():
                        return header
                    parsed = _split_card(card)
                    if parsed is not None:
                        header[parsed[0]] = parsed[1]
                block = handle.read(BLOCK_SIZE)
    except OSError as exc:
        raise FitsHeaderError(f"could not read {path}: {exc}") from exc

    raise FitsHeaderError(f"FITS header never ended: {path}")
