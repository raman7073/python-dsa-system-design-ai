"""Validation of custom censor words (extra words a user wants censored).

Kept apart from app.audio_censor, which imports WhisperX and torch: the API
validates words too, and must never load those.
"""

import re
from collections.abc import Iterable


class InvalidCustomWordsError(ValueError):
    """A custom word list breaks the rules in normalize_custom_words()."""


MAX_CUSTOM_WORDS = 100
MAX_CUSTOM_WORD_LENGTH = 40
# Letters (any language), digits, apostrophes and hyphens: "don't", "e-mail".
_CUSTOM_WORD = re.compile(r"[^\W_](?:(?:[^\W_]|['-])*[^\W_])?")


def normalize_custom_words(words: Iterable[str]) -> tuple[str, ...]:
    """Validate and normalize extra words to censor for one file.

    Strips and lower-cases each word, drops empty and repeated ones (keeping
    the first occurrence's order), and raises InvalidCustomWordsError for:
    - a phrase (a word with spaces): only single words can be censored
      reliably, because flagged words are checked one at a time;
    - a word longer than MAX_CUSTOM_WORD_LENGTH, or with characters other
      than letters, digits, apostrophes and hyphens;
    - more than MAX_CUSTOM_WORDS words.
    """
    result: dict[str, None] = {}  # ordered set
    for raw in words:
        word = raw.strip().lower()
        if not word:
            continue
        if any(ch.isspace() for ch in word):
            raise InvalidCustomWordsError(f"Only single words can be censored, not {raw!r}")
        if len(word) > MAX_CUSTOM_WORD_LENGTH:
            raise InvalidCustomWordsError(
                f"{raw!r} is longer than {MAX_CUSTOM_WORD_LENGTH} characters"
            )
        if not _CUSTOM_WORD.fullmatch(word):
            raise InvalidCustomWordsError(
                f"{raw!r} may only contain letters, digits, apostrophes and hyphens"
            )
        result[word] = None
    if len(result) > MAX_CUSTOM_WORDS:
        raise InvalidCustomWordsError(f"At most {MAX_CUSTOM_WORDS} custom words are allowed")
    return tuple(result)
