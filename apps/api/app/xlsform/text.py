"""Turn XLSForm label text into the words a phone agent would actually say."""

import re
import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

_REF = re.compile(r"\$\{([^}]+)\}")
_MD = re.compile(r"(\*\*|__|\*|_|#+ )")
_WS = re.compile(r"\s+")


def spoken_text(text: str | None) -> str:
    """Strip HTML and markdown, and replace ${var} references with the variable name."""
    if not text:
        return ""
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = _REF.sub(lambda m: m.group(1).replace("_", " "), text)
    text = _MD.sub("", text)
    return _WS.sub(" ", text).strip()


def word_count(text: str | None) -> int:
    return len(re.findall(r"\w+(?:['’-]\w+)*", spoken_text(text)))
