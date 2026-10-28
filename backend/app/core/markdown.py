"""Cleaning Markdown on save (PRD QB-06, SECURITY_AND_ACCESS.md T-26).

The real protection is the single client renderer, which never turns raw HTML into elements and
drops unsafe links. This is the second layer: what we store is plain Markdown with no HTML tags and
no script links, so nothing else that ever reads it (exports, emails) can be tricked either.

Code is left exactly as typed: fenced blocks, indented blocks and `inline code` may legitimately
show `<script>` in a programming question, and the renderer shows code as text.
"""

import html
import re

# Elements whose content is itself dangerous or invisible: removed with everything inside. One
# that is never closed takes the rest of the text with it, which is the safe way to fail.
_BLOCK_WITH_CONTENT = re.compile(
    r"<(script|style|iframe|object|noscript|template|textarea|title|xmp)\b[^>]*>.*?"
    r"(?:</\1\s*>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_CDATA = re.compile(r"<!\[CDATA\[.*?(?:\]\]>|\Z)", re.DOTALL)
# Any other tag (opening, closing, self-closing, or a declaration like <!DOCTYPE>).
_TAG = re.compile(r"</?[A-Za-z][^<>]*>|<![A-Za-z][^<>]*>")
# Link and image targets in Markdown: [text](target) and ![alt](target), plus <autolinks>.
# A bare target may contain balanced parentheses, e.g. (javascript:alert(1)).
_LINK_TARGET = re.compile(r"(!?\[[^\]]*\]\(\s*)(<[^>]*>|(?:[^()\s]|\([^()\s]*\))*)")
_REFERENCE = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*)(\S+)", re.MULTILINE)
# Browsers ignore control characters and whitespace inside a scheme ("java\tscript:").
_SCHEME_NOISE = re.compile(r"[\x00-\x20\x7f]+")
_SAFE_SCHEMES = ("http:", "https:", "mailto:")

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?:.|\n)*?(?<!`)\1(?!`)")


def _safe_target(target: str) -> str:
    # Markdown decodes entities in link targets, so "javascript&#58;" is a real scheme.
    probe = _SCHEME_NOISE.sub("", html.unescape(target.strip("<>"))).lower()
    scheme = re.match(r"^[a-z][a-z0-9+.-]*:", probe)
    if scheme and not probe.startswith(_SAFE_SCHEMES):
        return "#"  # javascript:, data:, vbscript:, file: ... become a dead link
    return target


def _clean_prose(text: str) -> str:
    """Clean text that is not code, keeping inline code spans as they are."""
    parts: list[str] = []
    last = 0
    for match in _INLINE_CODE.finditer(text):
        parts.append(_clean_plain(text[last : match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_clean_plain(text[last:]))
    return "".join(parts)


def _clean_plain(text: str) -> str:
    for pattern in (_BLOCK_WITH_CONTENT, _COMMENT, _CDATA):
        text = pattern.sub("", text)
    text = _TAG.sub("", text)
    text = _LINK_TARGET.sub(lambda m: m.group(1) + _safe_target(m.group(2)), text)
    return _REFERENCE.sub(lambda m: m.group(1) + _safe_target(m.group(2)), text)


def sanitize_markdown(text: str) -> str:
    """Markdown with HTML tags and unsafe link schemes removed; code untouched."""
    out: list[str] = []
    prose: list[str] = []
    fence: str | None = None
    previous_blank = True

    def flush() -> None:
        if prose:
            out.append(_clean_prose("".join(prose)))
            prose.clear()

    for line in text.splitlines(keepends=True):
        opener = _FENCE.match(line)
        if fence is not None:  # inside a fenced block: keep everything until its closing fence
            out.append(line)
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = None
        elif opener:
            flush()
            fence = opener.group(1)
            out.append(line)
        elif previous_blank and (line.startswith("    ") or line.startswith("\t")):
            flush()  # an indented code block starts after a blank line
            out.append(line)
            continue  # stays "after blank" so following indented lines are code too
        else:
            prose.append(line)
        previous_blank = not line.strip()
    flush()
    return "".join(out)
