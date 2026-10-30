"""Add ten classic coding problems (LeetCode 1 to 10, retold for stdin/stdout) to a teacher's
question bank, through the API, and validate each one.

    uv run --no-project --with requests python scripts/seed_coding_questions.py \
        --email teacher@college.edu [--base http://localhost:8080]

The password is asked for (or set XAMINER_PASSWORD). Problems the teacher already has (tagged
`leetcode-<n>`) are skipped, so running it twice is harmless.

Each problem has a Python reference solution. Expected outputs are made by running it here, and
the server's validation runs it again against every test case on the real runner.
"""

import argparse
import getpass
import os
import random
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

STARTERS = {
    "python312": "import sys\n\ndata = sys.stdin.read().split()\n# Your code here\n",
    "cpp17": (
        "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n"
        "    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    // Your code here\n"
        "    return 0;\n}\n"
    ),
    "java21": (
        "import java.io.*;\nimport java.util.*;\n\npublic class Main {\n"
        "    public static void main(String[] args) throws IOException {\n"
        "        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));\n"
        "        // Your code here\n    }\n}\n"
    ),
    "node22": (
        "const data = require('fs').readFileSync(0, 'utf8');\n"
        "const lines = data.split('\\n');\n// Your code here\n"
    ),
}


@dataclass
class Problem:
    number: int
    title: str
    difficulty: str  # easy, medium, hard
    topics: list[str]
    statement: str
    input_format: str
    output_format: str
    constraints: str
    reference: str
    public: list[str]
    hidden: list[str]
    time_limit_ms: int = 2000
    tags: list[str] = field(default_factory=list)

    @property
    def points(self) -> int:
        return {"easy": 10, "medium": 20, "hard": 30}[self.difficulty]


rng = random.Random(2026)


def _two_sum_big() -> str:
    n = 10_000
    nums = rng.sample(range(-(10**9), 10**9), n)
    i, j = 1234, 8765
    return f"{n} {nums[i] + nums[j]}\n{' '.join(map(str, nums))}\n"


def _digits(k: int) -> str:
    d = [rng.randint(0, 9) for _ in range(k)]
    d[-1] = rng.randint(1, 9)
    return " ".join(map(str, d))


def _word(n: int, alphabet: str) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def _sorted(n: int) -> str:
    return " ".join(map(str, sorted(rng.randint(-(10**6), 10**6) for _ in range(n))))


PROBLEMS = [
    Problem(
        1,
        "Two Sum",
        "easy",
        ["array", "hash-table"],
        "Given a list of integers and a target, find the two different positions whose values add "
        "up to the target. Exactly one such pair exists.",
        "The first line has `n` and `target`. The second line has `n` integers.",
        "Print the two positions (counting from 0), smaller first, separated by a space.",
        "2 ≤ n ≤ 10⁴; values and target between −10⁹ and 10⁹; exactly one answer.",
        """import sys
d = sys.stdin.read().split()
n, target = int(d[0]), int(d[1])
seen = {}
for i, x in enumerate(map(int, d[2:2 + n])):
    if target - x in seen:
        print(seen[target - x], i)
        break
    seen.setdefault(x, i)
""",
        ["4 9\n2 7 11 15\n", "3 6\n3 2 4\n"],
        ["2 6\n3 3\n", "5 -8\n-1 -2 -3 -4 -5\n", "4 0\n0 4 3 0\n", _two_sum_big()],
    ),
    Problem(
        2,
        "Add Two Numbers",
        "medium",
        ["linked-list", "math"],
        "Two non-negative numbers are given as lists of digits in **reverse order** (the ones digit "
        "first), like a linked list. Add them and give the sum the same way.",
        "Two lines, one per number: its digits, ones digit first, separated by spaces.",
        "The digits of the sum, ones digit first, separated by spaces.",
        "1 to 100 digits each; no leading zeros except the number 0 itself.",
        """import sys
a, b = (list(map(int, line.split())) for line in sys.stdin.read().strip().split("\\n")[:2])
out, carry = [], 0
for i in range(max(len(a), len(b))):
    s = (a[i] if i < len(a) else 0) + (b[i] if i < len(b) else 0) + carry
    out.append(s % 10)
    carry = s // 10
if carry:
    out.append(carry)
print(" ".join(map(str, out)))
""",
        ["2 4 3\n5 6 4\n", "0\n0\n"],
        ["9 9 9 9 9 9 9\n9 9 9 9\n", "1\n9 9 9\n", "5\n5\n", f"{_digits(100)}\n{_digits(73)}\n"],
    ),
    Problem(
        3,
        "Longest Substring Without Repeating Characters",
        "medium",
        ["string", "sliding-window"],
        "Find the length of the longest run of consecutive characters in a string where no "
        "character appears twice.",
        "One line with the string `s` (letters, digits and symbols, no spaces). It may be empty.",
        "The length of the longest such substring.",
        "0 ≤ length of s ≤ 5·10⁴.",
        """import sys
d = sys.stdin.read().split()
s = d[0] if d else ""
last, start, best = {}, 0, 0
for i, c in enumerate(s):
    if last.get(c, -1) >= start:
        start = last[c] + 1
    last[c] = i
    best = max(best, i - start + 1)
print(best)
""",
        ["abcabcbb\n", "bbbbb\n"],
        [
            "pwwkew\n",
            "\n",
            "dvdf\n",
            "abba\n",
            _word(50_000, "abcdefghijklmnopqrstuvwxyz0123456789") + "\n",
        ],
    ),
    Problem(
        4,
        "Median of Two Sorted Arrays",
        "hard",
        ["array", "binary-search"],
        "Two lists of integers are each sorted from smallest to largest. Find the median of all "
        "their values together. Aim for better than merging them (O(log(m + n)) is possible).",
        "The first line has `m` and `n`. The second line has the `m` values of the first list and "
        "the third the `n` values of the second (a line may be empty).",
        "The median with exactly 5 decimals, like `2.50000`.",
        "0 ≤ m, n ≤ 1000; 1 ≤ m + n; values between −10⁶ and 10⁶.",
        """import sys
lines = sys.stdin.read().split("\\n")
m, n = map(int, lines[0].split())
a = list(map(int, lines[1].split())) if m else []
b = list(map(int, lines[2].split())) if n else []
c = sorted(a + b)
k = len(c)
median = c[k // 2] if k % 2 else (c[k // 2 - 1] + c[k // 2]) / 2
print(f"{median:.5f}")
""",
        ["2 1\n1 3\n2\n", "2 2\n1 2\n3 4\n"],
        [
            "0 1\n\n1\n",
            "1 0\n-5\n\n",
            "3 4\n1 1 1\n1 1 1 1\n",
            f"1000 999\n{_sorted(1000)}\n{_sorted(999)}\n",
        ],
    ),
    Problem(
        5,
        "Longest Palindromic Substring",
        "medium",
        ["string", "dynamic-programming"],
        "Find the longest run of consecutive characters that reads the same forwards and "
        "backwards. If several have the same length, give the one that starts first.",
        "One line with the string `s` (letters and digits).",
        "The longest palindromic substring.",
        "1 ≤ length of s ≤ 1000.",
        """import sys
s = sys.stdin.read().split()[0]
best = (0, 1)
for centre in range(2 * len(s) - 1):
    lo, hi = centre // 2, centre // 2 + centre % 2
    while lo >= 0 and hi < len(s) and s[lo] == s[hi]:
        lo, hi = lo - 1, hi + 1
    if hi - lo - 1 > best[1] - best[0]:
        best = (lo + 1, hi)
print(s[best[0]:best[1]])
""",
        ["babad\n", "cbbd\n"],
        ["a\n", "ac\n", "forgeeksskeegfor\n", _word(1000, "ab") + "\n"],
    ),
    Problem(
        6,
        "Zigzag Conversion",
        "medium",
        ["string"],
        "Write the string in a zigzag over `numRows` rows: down the rows, then diagonally back up, "
        "and so on. Then read the rows one after another. For `PAYPALISHIRING` on 3 rows:\n\n"
        "```\nP   A   H   N\nA P L S I I G\nY   I   R\n```\n\nreads `PAHNAPLSIIGYIR`.",
        "The first line has the string `s` (letters, `,` and `.`). The second line has `numRows`.",
        "The string read row by row.",
        "1 ≤ length of s ≤ 1000; 1 ≤ numRows ≤ 1000.",
        """import sys
s, rows = sys.stdin.read().split()[:2]
rows = int(rows)
if rows == 1:
    print(s)
else:
    out = [""] * rows
    r, step = 0, 1
    for c in s:
        out[r] += c
        if r == 0:
            step = 1
        elif r == rows - 1:
            step = -1
        r += step
    print("".join(out))
""",
        ["PAYPALISHIRING\n3\n", "PAYPALISHIRING\n4\n"],
        ["A\n1\n", "AB\n1\n", "ABCDE\n10\n", _word(1000, "abcxyz,.") + "\n7\n"],
    ),
    Problem(
        7,
        "Reverse Integer",
        "medium",
        ["math"],
        "Reverse the digits of a 32-bit signed integer, keeping its sign. If the result does not "
        "fit in a 32-bit signed integer (−2³¹ to 2³¹ − 1), print 0.",
        "One integer `x`.",
        "The reversed integer, or 0.",
        "−2³¹ ≤ x ≤ 2³¹ − 1.",
        """x = int(input())
r = int(str(abs(x))[::-1]) * (1 if x >= 0 else -1)
print(r if -2**31 <= r <= 2**31 - 1 else 0)
""",
        ["123\n", "-123\n"],
        ["120\n", "0\n", "1534236469\n", "-2147483648\n", "-2147483412\n"],
    ),
    Problem(
        8,
        "String to Integer (atoi)",
        "medium",
        ["string"],
        "Turn a string into a 32-bit signed integer like C's `atoi`:\n\n"
        "1. Skip leading spaces.\n2. An optional `+` or `-` gives the sign.\n"
        "3. Read digits until a non-digit or the end; no digits means 0.\n"
        "4. Clamp to −2³¹ … 2³¹ − 1.",
        "One line with the string `s` (it may start with spaces).",
        "The integer.",
        "0 ≤ length of s ≤ 200; letters, digits, spaces, `+`, `-` and `.`.",
        """import sys
s = sys.stdin.readline().rstrip("\\r\\n").lstrip(" ")
sign, i = 1, 0
if i < len(s) and s[i] in "+-":
    sign = -1 if s[i] == "-" else 1
    i += 1
n = 0
while i < len(s) and s[i].isdigit():
    n = n * 10 + int(s[i])
    i += 1
print(max(-2**31, min(2**31 - 1, sign * n)))
""",
        ["42\n", "   -042\n"],
        ["1337c0d3\n", "0-1\n", "words and 987\n", "-91283472332\n", "+-12\n", "\n", "   +0 123\n"],
    ),
    Problem(
        9,
        "Palindrome Number",
        "easy",
        ["math"],
        "Say whether an integer reads the same forwards and backwards. Negative numbers never do. "
        "Can you do it without turning the number into a string?",
        "One integer `x`.",
        "`true` or `false`.",
        "−2³¹ ≤ x ≤ 2³¹ − 1.",
        """x = int(input())
print("true" if x >= 0 and str(x) == str(x)[::-1] else "false")
""",
        ["121\n", "-121\n"],
        ["10\n", "0\n", "1234554321\n", "2147483647\n", "1000021\n"],
    ),
    Problem(
        10,
        "Regular Expression Matching",
        "hard",
        ["string", "dynamic-programming", "recursion"],
        "Does the pattern `p` match the **whole** string `s`? In the pattern, `.` matches any one "
        "character and `*` matches zero or more of the character before it.",
        "The first line has `s` (lowercase letters, may be empty). The second line has `p` "
        "(lowercase letters, `.` and `*`; every `*` follows a letter or `.`).",
        "`true` or `false`.",
        "0 ≤ length of s ≤ 20; 1 ≤ length of p ≤ 20.",
        """import sys
from functools import lru_cache
lines = sys.stdin.read().split("\\n")
s, p = lines[0].strip(), lines[1].strip()

@lru_cache(maxsize=None)
def match(i, j):
    if j == len(p):
        return i == len(s)
    first = i < len(s) and p[j] in (s[i], ".")
    if j + 1 < len(p) and p[j + 1] == "*":
        return match(i, j + 2) or (first and match(i + 1, j))
    return first and match(i + 1, j + 1)

print("true" if match(0, 0) else "false")
""",
        ["aa\na\n", "aa\na*\n"],
        [
            "ab\n.*\n",
            "aab\nc*a*b\n",
            "mississippi\nmis*is*p*.\n",
            "\na*b*\n",
            "aaaaaaaaaaaaaaaaaaab\na*a*a*a*a*a*a*a*a*c\n",
        ],
    ),
]


def expected(reference: str, case: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", reference], input=case, capture_output=True, text=True, timeout=30
    )
    if done.returncode != 0:
        raise SystemExit(f"Reference failed on {case[:40]!r}: {done.stderr}")
    return done.stdout


Call = Callable[..., Any]


def connect(base: str, email: str, password: str) -> Call:
    """Log in; returns call(method, path, **requests_kwargs) -> JSON, stopping on any error."""
    api = f"{base.rstrip('/')}/api/v1"
    login = requests.post(f"{api}/auth/login", json={"email": email, "password": password})
    if not login.ok:
        raise SystemExit(f"Login failed: {login.text}")
    h = {"Authorization": "Bearer " + login.json()["access_token"]}

    def call(method: str, path: str, **kw: Any) -> Any:
        r = requests.request(method, api + path, headers=h, timeout=60, **kw)
        if not r.ok:
            raise SystemExit(f"{method} {path}: {r.status_code} {r.text}")
        return r.json() if r.content else None

    return call


def existing(call: Call, p: Problem) -> str | None:
    found = call("GET", "/questions", params={"tag": f"leetcode-{p.number}", "owner": "mine"})
    return found["data"][0]["id"] if found["data"] else None


def add(call: Call, p: Problem) -> str:
    """Create the question, its coding setup, tests and reference, and start validating it."""
    q: str = call(
        "POST",
        "/questions",
        json={
            "type": "CODING",
            "tags": ["leetcode", f"leetcode-{p.number}", p.difficulty, *p.topics],
            "body": f"## {p.number}. {p.title}\n\n{p.statement}",
            "points": str(p.points),
        },
    )["id"]
    call(
        "PUT",
        f"/questions/{q}/coding",
        json={
            "input_format": p.input_format,
            "output_format": p.output_format,
            "constraints": p.constraints,
            "allowed_languages": [
                {"language_key": key, "starter_code": code} for key, code in STARTERS.items()
            ],
            "time_limit_ms": p.time_limit_ms,
            "comparison_mode": "TRIM",
            "partial_scoring": True,
        },
    )
    for visibility, cases in (("PUBLIC", p.public), ("HIDDEN", p.hidden)):
        for case in cases:
            call(
                "POST",
                f"/questions/{q}/test-cases",
                json={
                    "input": case,
                    "expected_output": expected(p.reference, case),
                    "visibility": visibility,
                },
            )
    call("PUT", f"/questions/{q}/reference-solutions/python312", json={"source": p.reference})
    call("POST", f"/questions/{q}/validate")
    return q


def validation(call: Call, q: str) -> str:
    """Wait for the question's validation to finish; returns PASSED or FAILED."""
    for _ in range(180):
        status: str = call("GET", f"/questions/{q}")["coding"]["validation_status"]
        if status != "VALIDATING":
            return status
        time.sleep(1)
    return "VALIDATING"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="a teacher's email")
    parser.add_argument("--base", default="http://localhost:8080")
    args = parser.parse_args()
    password = os.environ.get("XAMINER_PASSWORD") or getpass.getpass("Password: ")
    call = connect(args.base, args.email, password)

    started: list[tuple[Problem, str]] = []
    for p in PROBLEMS:
        if existing(call, p):
            print(f"skip   {p.number}. {p.title} (already there)")
            continue
        started.append((p, add(call, p)))
        print(f"added  {p.number}. {p.title} ({len(p.public)} public, {len(p.hidden)} hidden)")
    for p, q in started:
        print(f"{validation(call, q):<8} {p.number}. {p.title}")


if __name__ == "__main__":
    main()
