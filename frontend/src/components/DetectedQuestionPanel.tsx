export interface DetectedQuestionPanelProps {
  id: string | null;
  text: string | null;
}

export function DetectedQuestionPanel({ id, text }: DetectedQuestionPanelProps) {
  return (
    <section className="panel">
      <h2>Detected question</h2>
      {text ? (
        <p className="detected-question" data-question-id={id ?? undefined}>
          {text}
        </p>
      ) : (
        <p className="placeholder">
          Ask a question like "Explain Python generators" — it will appear here
          once the detector fires.
        </p>
      )}
    </section>
  );
}
