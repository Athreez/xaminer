import Markdown, { defaultUrlTransform, type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * The one place question text, options, rubrics and feedback are turned into HTML
 * (FRONTEND_SPEC § 3.2, threat T-26). Raw HTML in the Markdown is never rendered, the sanitiser
 * keeps only an allow-list of elements and attributes, and links can only be http(s) or mailto.
 * The server cleans Markdown on save as well; this does not rely on it.
 */
const SAFE_SCHEMES = /^(https?:|mailto:|\/|#)/i;

function urlTransform(url: string): string {
  const safe = defaultUrlTransform(url); // already drops javascript:, vbscript:, data: ...
  return safe && (SAFE_SCHEMES.test(safe) || !/^[a-z][a-z0-9+.-]*:/i.test(safe)) ? safe : "";
}

const components: Components = {
  // External links open in a new tab without giving that page a handle back to ours.
  a: ({ node: _node, href, children, ...props }) => {
    const external = href?.startsWith("http");
    return (
      <a
        {...props}
        href={href}
        {...(external ? { target: "_blank", rel: "noopener noreferrer nofollow" } : {})}
      >
        {children}
      </a>
    );
  },
  img: ({ node: _node, alt, ...props }) => (
    <img {...props} alt={alt ?? ""} loading="lazy" referrerPolicy="no-referrer" />
  ),
};

export function MarkdownView({
  text,
  className,
  images,
}: {
  text: string;
  className?: string;
  /** Signed links for image references (`/api/v1/images/<id>`) in the text, from the API. */
  images?: Record<string, string>;
}) {
  return (
    <div className={cn("markdown", className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        skipHtml
        urlTransform={(url) => urlTransform(images?.[url] ?? url)}
        components={components}
      >
        {text}
      </Markdown>
    </div>
  );
}
