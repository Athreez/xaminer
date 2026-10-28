"""The Markdown sanitiser (PRD QB-06, threat T-26). Each payload must come out harmless."""

import html

import pytest

from app.core.markdown import sanitize_markdown

DANGEROUS = [
    "<script>alert(1)</script>",
    "<SCRIPT SRC=//evil.example/x.js></SCRIPT>",
    "<img src=x onerror=alert(1)>",
    '<svg onload="alert(1)">',
    '<iframe src="https://evil.example"></iframe>',
    '<object data="evil.swf"></object>',
    '<embed src="evil.swf">',
    "<style>body{display:none}</style>",
    '<a href="javascript:alert(1)">click</a>',
    '<div style="background:url(javascript:alert(1))">x</div>',
    "<!-- <script>alert(1)</script> -->",
    "<![CDATA[<script>alert(1)</script>]]>",
    '<details open ontoggle="alert(1)">',
    '<body onload="alert(1)">',
    '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">',
    '<form action="javascript:alert(1)"><button>go</button></form>',
    "<<script>script>alert(1)<</script>/script>",
]

DANGEROUS_LINKS = [
    "[click](javascript:alert(1))",
    "[click](javascript&#58;alert(1))",  # Markdown decodes entities in link targets
    "[click](javascript&colon;alert(1))",
    "[click](&#x6A;avascript:alert(1))",
    "[click](JaVaScRiPt:alert(1))",
    "[click]( javascript:alert(1) )",
    "[click](<javascript:alert(1)>)",
    "[click](vbscript:msgbox(1))",
    "![img](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
    "[ref]: javascript:alert(1)",
    "[click](file:///etc/passwd)",
]


@pytest.mark.parametrize("payload", DANGEROUS)
def test_html_is_removed(payload: str) -> None:
    cleaned = sanitize_markdown(f"Before {payload} after")
    assert "<" not in cleaned.replace("&lt;", "") or "<" not in _tags(cleaned), cleaned
    lowered = cleaned.lower()
    for marker in (
        "<script",
        "onerror",
        "onload",
        "ontoggle",
        "<iframe",
        "<object",
        "<embed",
        "<style",
        "javascript:",
        "<svg",
        "<img",
        "<meta",
        "<form",
    ):
        assert marker not in lowered, (payload, cleaned)
    assert cleaned.startswith("Before") and cleaned.endswith("after")


@pytest.mark.parametrize(
    "payload",
    ["<script>alert(1)", "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>"],
    ids=["unclosed-script", "mxss-unclosed-style"],
)
def test_unclosed_dangerous_elements_take_the_rest(payload: str) -> None:
    assert sanitize_markdown(f"Before {payload} after") == "Before "


def _tags(text: str) -> str:
    import re

    return "".join(re.findall(r"</?[A-Za-z][^>]*>", text))


@pytest.mark.parametrize("payload", DANGEROUS_LINKS)
def test_unsafe_link_schemes_are_neutralised(payload: str) -> None:
    cleaned = html.unescape(sanitize_markdown(payload)).lower().replace(" ", "")
    for scheme in ("javascript:", "vbscript:", "data:", "file:"):
        assert scheme not in cleaned, (payload, cleaned)


@pytest.mark.parametrize(
    "text",
    [
        "Plain **bold** and _italic_ text.",
        "Is a < b and c > d? What about x <= y?",
        "Use `<script>` tags carefully.",
        "Inline ``code with ` backtick <b>``.",
        "```html\n<script>alert('example')</script>\n```",
        "~~~\n<iframe src=x></iframe>\n~~~",
        "Text\n\n    <div onclick=x>indented code</div>\n",
        "[Docs](https://docs.python.org/3/) and [mail](mailto:t@abc.edu) and [rel](/help)",
        "![diagram](https://example.edu/tree.png)",
        "| a | b |\n|---|---|\n| 1 | 2 |",
        "Generics like List<String> and Map<K, V>",
    ],
    ids=[
        "markdown",
        "comparisons",
        "inline-code",
        "double-backtick",
        "fenced",
        "tilde-fence",
        "indented-code",
        "safe-links",
        "image",
        "table",
        "generics",
    ],
)
def test_ordinary_content_is_unchanged(text: str) -> None:
    if "List<String>" in text:
        # Looks like a tag, so it's removed outside code; teachers should write it as code.
        assert sanitize_markdown(text) == "Generics like List and Map"
        assert sanitize_markdown("Generics like `List<String>`") == "Generics like `List<String>`"
        return
    assert sanitize_markdown(text) == text


def test_code_fence_must_close_with_the_same_marker() -> None:
    text = "```\n~~~\n<script>x</script>\n```\nafter <b>bold</b>"
    assert sanitize_markdown(text) == "```\n~~~\n<script>x</script>\n```\nafter bold"


def test_links_with_parentheses() -> None:
    wiki = "[tree](https://en.wikipedia.org/wiki/Tree_(data_structure))"
    assert sanitize_markdown(wiki) == wiki
    assert sanitize_markdown("[x](javascript:alert(1)) rest") == "[x](#) rest"
