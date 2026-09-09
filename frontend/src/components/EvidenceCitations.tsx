import type { EvidenceCitation } from "../api/types";

type EvidenceCitationsProps = {
  citations?: EvidenceCitation[];
};

export default function EvidenceCitations({ citations }: EvidenceCitationsProps) {
  if (!citations?.length) return null;

  return (
    <details className="citation-details">
      <summary>原文证据 {citations.length}</summary>
      <div className="citation-list">
        {citations.slice(0, 3).map((citation) => (
          <blockquote className="citation-card" key={citation.id}>
            <div className="citation-meta">
              {citation.document_title || citation.document_id}
              {citation.evidence_unit_id ? ` · ${citation.evidence_unit_id}` : ""}
            </div>
            <div className="citation-quote">{citation.quote || citation.span_texts.join(" ")}</div>
            {citation.heading_path?.length ? (
              <div className="citation-location">{citation.heading_path.join(" / ")}</div>
            ) : null}
          </blockquote>
        ))}
      </div>
    </details>
  );
}
