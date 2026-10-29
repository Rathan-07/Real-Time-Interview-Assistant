import { useCallback, useEffect, useRef, useState } from "react";

export type MicPermissionState = "prompt" | "granted" | "denied";

export interface UseAudioStreamOptions {
  onChunk: (chunk: Blob) => void;
  timesliceMs?: number;
  mimeType?: string;
}

export interface UseAudioStream {
  recording: boolean;
  permission: MicPermissionState;
  error: string | null;
  start: () => Promise<void>;
  stop: () => void;
}

const DEFAULT_MIME = "audio/webm;codecs=opus";
const DEFAULT_TIMESLICE_MS = 250;

/**
 * Capture microphone audio via MediaRecorder → WebM/Opus.
 *
 * Design choices worth defending in interview:
 * - MediaRecorder (not AudioWorklet) because Deepgram sniffs the WebM header,
 *   so we don't have to downsample or hand-roll packet framing.
 * - timeslice 250 ms gives Deepgram enough bytes to detect the container but
 *   keeps first-token latency reasonable; Phase 5 may tune this.
 * - Permission is requested only when `start()` is called — never on mount.
 * - stop() releases MediaStreamTrack handles so the browser mic indicator
 *   actually goes away.
 */
export function useAudioStream(opts: UseAudioStreamOptions): UseAudioStream {
  const [recording, setRecording] = useState(false);
  const [permission, setPermission] = useState<MicPermissionState>("prompt");
  const [error, setError] = useState<string | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);

  // Keep the callback fresh without re-creating start/stop closures.
  const onChunkRef = useRef(opts.onChunk);
  useEffect(() => {
    onChunkRef.current = opts.onChunk;
  }, [opts.onChunk]);

  const mimeType = opts.mimeType ?? DEFAULT_MIME;
  const timeslice = opts.timesliceMs ?? DEFAULT_TIMESLICE_MS;

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    const stream = streamRef.current;
    recorderRef.current = null;
    streamRef.current = null;

    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        /* already stopping */
      }
    }
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
    }
    setRecording(false);
  }, []);

  const start = useCallback(async () => {
    setError(null);

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      setError("This browser does not expose getUserMedia.");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      setError("This browser does not support MediaRecorder.");
      return;
    }
    if (!MediaRecorder.isTypeSupported(mimeType)) {
      setError(`Browser does not support ${mimeType}. Try Chrome or Firefox.`);
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      const name = (err as { name?: string })?.name ?? "Error";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setPermission("denied");
        setError("Microphone permission denied.");
      } else if (name === "NotFoundError" || name === "OverconstrainedError") {
        setError("No microphone available.");
      } else {
        setError(`Microphone error: ${name}`);
      }
      return;
    }

    setPermission("granted");
    streamRef.current = stream;

    const recorder = new MediaRecorder(stream, { mimeType });
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) onChunkRef.current(e.data);
    };
    recorder.onerror = (e) => {
      const errName =
        (e as unknown as { error?: { name?: string } }).error?.name ?? "unknown";
      setError(`Recorder error: ${errName}`);
    };

    try {
      recorder.start(timeslice);
    } catch (err) {
      const name = (err as { name?: string })?.name ?? "Error";
      setError(`Failed to start recorder: ${name}`);
      stop();
      return;
    }

    recorderRef.current = recorder;
    setRecording(true);
  }, [mimeType, timeslice, stop]);

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return { recording, permission, error, start, stop };
}
