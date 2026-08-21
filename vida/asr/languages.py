"""Whisper's language table, and how to get an ISO-639-1 code out of a name.

Whisper reports the language it decoded as an English *name* — ``"English"``,
``"Burmese"`` — but the ``language`` request parameter only accepts a code.
Feeding a detected language back in as a hint therefore needs a translation
step, which is what this module is.
"""

from __future__ import annotations

__all__ = ["LANGUAGE_NAMES", "to_code"]

LANGUAGE_NAMES: dict[str, str] = {
    "en": "english", "zh": "chinese", "de": "german", "es": "spanish",
    "ru": "russian", "ko": "korean", "fr": "french", "ja": "japanese",
    "pt": "portuguese", "tr": "turkish", "pl": "polish", "ca": "catalan",
    "nl": "dutch", "ar": "arabic", "sv": "swedish", "it": "italian",
    "id": "indonesian", "hi": "hindi", "fi": "finnish", "vi": "vietnamese",
    "he": "hebrew", "uk": "ukrainian", "el": "greek", "ms": "malay",
    "cs": "czech", "ro": "romanian", "da": "danish", "hu": "hungarian",
    "ta": "tamil", "no": "norwegian", "th": "thai", "ur": "urdu",
    "hr": "croatian", "bg": "bulgarian", "lt": "lithuanian", "la": "latin",
    "mi": "maori", "ml": "malayalam", "cy": "welsh", "sk": "slovak",
    "te": "telugu", "fa": "persian", "lv": "latvian", "bn": "bengali",
    "sr": "serbian", "az": "azerbaijani", "sl": "slovenian", "kn": "kannada",
    "et": "estonian", "mk": "macedonian", "br": "breton", "eu": "basque",
    "is": "icelandic", "hy": "armenian", "ne": "nepali", "mn": "mongolian",
    "bs": "bosnian", "kk": "kazakh", "sq": "albanian", "sw": "swahili",
    "gl": "galician", "mr": "marathi", "pa": "punjabi", "si": "sinhala",
    "km": "khmer", "sn": "shona", "yo": "yoruba", "so": "somali",
    "af": "afrikaans", "oc": "occitan", "ka": "georgian", "be": "belarusian",
    "tg": "tajik", "sd": "sindhi", "gu": "gujarati", "am": "amharic",
    "yi": "yiddish", "lo": "lao", "uz": "uzbek", "fo": "faroese",
    "ht": "haitian creole", "ps": "pashto", "tk": "turkmen", "nn": "nynorsk",
    "mt": "maltese", "sa": "sanskrit", "lb": "luxembourgish", "my": "myanmar",
    "bo": "tibetan", "tl": "tagalog", "mg": "malagasy", "as": "assamese",
    "tt": "tatar", "haw": "hawaiian", "ln": "lingala", "ha": "hausa",
    "ba": "bashkir", "jw": "javanese", "su": "sundanese", "yue": "cantonese",
}
"""Every language Whisper knows, code to the name it reports."""

# Names Whisper also answers to, and the ones the models actually emit for
# languages whose canonical entry above is a different word: a Burmese
# recording comes back as "Burmese", never as "myanmar".
_ALIASES: dict[str, str] = {
    "burmese": "my",
    "valencian": "ca",
    "flemish": "nl",
    "haitian": "ht",
    "letzeburgesch": "lb",
    "pushto": "ps",
    "panjabi": "pa",
    "moldavian": "ro",
    "moldovan": "ro",
    "sinhalese": "si",
    "castilian": "es",
    "mandarin": "zh",
}

_BY_NAME = {name: code for code, name in LANGUAGE_NAMES.items()} | _ALIASES


def to_code(value: str | None) -> str | None:
    """Normalise a language name or code to ISO-639-1.

    Accepts what Whisper reports (``"English"``), what a caller is more likely
    to type (``"en"``, ``"EN"``), and the aliases above. Returns ``None`` for
    anything unrecognised, which callers should read as "don't pin a language"
    rather than as an error — a wrong pin is far more damaging than none.
    """
    if not value:
        return None
    key = value.strip().lower()
    if key in LANGUAGE_NAMES:
        return key
    return _BY_NAME.get(key)
