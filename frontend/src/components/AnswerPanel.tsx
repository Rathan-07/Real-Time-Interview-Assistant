import { useState } from "react";

export interface AnswerMetrics {
  firstTokenMs: number;
  totalMs: number;
  chunkCount: number;
  charCount: number;
}

export interface AnswerPanelProps {
  questionId: string | null;
  text: string;
  streaming: boolean;
  metrics: AnswerMetrics | null;
}

export function AnswerPanel({
  questionId,
  text,
  streaming,
  metrics,
}: AnswerPanelProps) {
  const hasAny = text.length > 0;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard denied */
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>
          Answer{" "}
          {streaming && <span className="streaming-dot" aria-label="streaming" />}
        </h2>
        <div className="panel-header-right">
          {metrics && (
            <span
              className="metric-badge"
              title={`${metrics.chunkCount} chunks · ${metrics.charCount} chars · total ${metrics.totalMs} ms`}
            >
              {metrics.firstTokenMs} ms to first token
            </span>
          )}
          {hasAny && !streaming && (
            <button type="button" className="copy-button" onClick={copy}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
          )}
        </div>
      </div>

      {!hasAny && !streaming && (
        <p className="placeholder">
          A grounded answer streams here once the detector fires on a real
          question.
        </p>
      )}
      {!hasAny && streaming && <p className="placeholder">Thinking…</p>}
      {hasAny && (
        <p
          className="answer-text"
          data-question-id={questionId ?? undefined}
        >
          {text}
          {streaming && <span className="cursor">▍</span>}
        </p>
      )}
    </section>
  );
}
