import type { ReactNode } from "react";

/** Minimal formatting for model answers: **bold** and "- " bullet lines. Everything else is
 *  plain text (no HTML is ever injected). `renderInline` handles citations within a line. */
export function RichText({ text, renderInline }: {
  text: string;
  renderInline: (segment: string, key: string) => ReactNode;
}) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let bullets: ReactNode[] = [];
  const flush = (key: string) => {
    if (bullets.length) blocks.push(<ul key={key} className="my-1 list-disc space-y-1 pl-5">{bullets}</ul>);
    bullets = [];
  };
  const inline = (line: string, key: string) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**")
        ? <strong key={`${key}-${i}`}>{renderInline(part.slice(2, -2), `${key}-${i}`)}</strong>
        : renderInline(part, `${key}-${i}`));
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      bullets.push(<li key={i}>{inline(bullet[1], `l${i}`)}</li>);
      return;
    }
    flush(`ul${i}`);
    if (line.trim()) blocks.push(<p key={i} className="my-1">{inline(line, `p${i}`)}</p>);
  });
  flush("ul-end");
  return <div>{blocks}</div>;
}
