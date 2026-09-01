import "./PolicyText.css";

/**
 * Renders a policy version's plain-language text.
 *
 * **Not a markdown library**, deliberately. The only formatting this text
 * ever uses is a paragraph break, a `## ` subheading, and an occasional
 * `**bold**` lead-in - what `create_policy_version`'s own author needs,
 * nothing a general parser would earn its bundle size for.
 */
export function PolicyText({ markdown }: { markdown: string }) {
  const paragraphs = markdown.trim().split(/\n\s*\n/);

  return (
    <div className="policy-text">
      {paragraphs.map((paragraph, index) => {
        const trimmed = paragraph.trim();
        if (trimmed.startsWith("## ")) {
          return <h3 key={index}>{trimmed.slice(3)}</h3>;
        }
        return <p key={index}>{renderInline(trimmed)}</p>;
      })}
    </div>
  );
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={index}>{part.slice(2, -2)}</strong>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}
