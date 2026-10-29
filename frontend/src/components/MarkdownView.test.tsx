import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MarkdownView } from "./MarkdownView";

const render = (text: string) => renderToStaticMarkup(<MarkdownView text={text} />);

// The same kinds of payload the server's sanitiser is tested with (threat T-26).
const PAYLOADS = [
  "<script>alert(1)</script>",
  "<img src=x onerror=alert(1)>",
  '<svg onload="alert(1)">',
  '<iframe src="https://evil.example"></iframe>',
  '<a href="javascript:alert(1)">click</a>',
  '<div style="background:url(javascript:alert(1))">x</div>',
  '<details open ontoggle="alert(1)">x</details>',
  "[click](javascript:alert(1))",
  "[click](JaVaScRiPt:alert(1))",
  "[click](javascript&#58;alert(1))",
  "[click](vbscript:msgbox(1))",
  "![img](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
  "[ref]: javascript:alert(1)\n\n[click][ref]",
];

describe("MarkdownView", () => {
  it.each(PAYLOADS)("renders %s harmlessly", (payload) => {
    const html = render(`Before ${payload} after`).toLowerCase();
    for (const bad of [
      "<script",
      "<iframe",
      "<svg",
      "<div style",
      "onerror=",
      "onload=",
      "ontoggle=",
    ]) {
      expect(html).not.toContain(bad);
    }
    // Words may remain as text; what matters is that no link or image points anywhere unsafe.
    expect(html).not.toMatch(/(href|src)="\s*(javascript|vbscript|data):/);
  });

  it("drops unsafe targets of reference-style links", () => {
    const html = render("[click][ref]\n\n[ref]: javascript:alert(1)").toLowerCase();
    expect(html).not.toContain("javascript:");
  });

  it("renders ordinary Markdown", () => {
    const html = render(
      "## Title\n\n**bold** and `<b>code</b>`\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nprint('<x>')\n```",
    );
    expect(html).toContain("<h2>Title</h2>");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<code>&lt;b&gt;code&lt;/b&gt;</code>"); // code shown as text
    expect(html).toContain("<table>");
    expect(html).toContain("print(&#x27;&lt;x&gt;&#x27;)");
  });

  it("opens external links safely and keeps relative ones", () => {
    const html = render("[docs](https://docs.python.org) [help](/help) [mail](mailto:a@b.edu)");
    expect(html).toContain(
      'href="https://docs.python.org" target="_blank" rel="noopener noreferrer nofollow"',
    );
    expect(html).toContain('href="/help"');
    expect(html).not.toMatch(/href="\/help"[^>]*target/);
    expect(html).toContain('href="mailto:a@b.edu"');
  });

  it("loads images lazily without sending the referrer", () => {
    const html = render("![tree](https://example.edu/tree.png)");
    expect(html).toContain('src="https://example.edu/tree.png"');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('referrerPolicy="no-referrer"');
  });

  it("swaps image references for the signed links it is given", () => {
    const ref = "/api/v1/images/01a18670-115f-74ce-8ce1-4d136bfe1fe6";
    const signed = "http://localhost:8080/images/x.webp?X-Amz-Signature=abc";
    const html = renderToStaticMarkup(
      <MarkdownView text={`![chart](${ref})`} images={{ [ref]: signed }} />,
    );
    expect(html).toContain(`src="${signed.replace("&", "&amp;")}"`);
    expect(render(`![chart](${ref})`)).toContain(`src="${ref}"`); // no table: left as is
  });
});
