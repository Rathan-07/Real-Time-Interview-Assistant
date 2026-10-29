export interface AnswerPanelProps {
  questionId: string | null;
  text: string;
  streaming: boolean;
}

export function AnswerPanel({ questionId, text, streaming }: AnswerPanelProps) {
  const hasAny = text.length > 0;
  return (
    <section className="panel">
      <h2>
        Answer{" "}
        {streaming && <span className="streaming-dot" aria-label="streaming" />}
      </h2>
      {!hasAny && !streaming && (
        <p className="placeholder">
          A grounded answer streams here once the detector fires on a real
          question.
        </p>
      )}
      {!hasAny && streaming && (
        <p className="placeholder">Thinking…</p>
      )}
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
