export interface TranscriptPanelProps {
  finals: string[];
  interim: string;
}

export function TranscriptPanel({ finals, interim }: TranscriptPanelProps) {
  const hasAny = finals.length > 0 || interim.length > 0;

  return (
    <section className="panel">
      <h2>Transcript</h2>
      {!hasAny && (
        <p className="placeholder">
          Say something after you start listening — interim words appear here in
          grey, finalized text in white.
        </p>
      )}
      {finals.length > 0 && (
        <p className="transcript-final">{finals.join(" ")}</p>
      )}
      {interim && <p className="transcript-interim">{interim}</p>}
    </section>
  );
}
