import type { ClientEvent, ServerEvent } from "../types/events";

export type WsStatus = "disconnected" | "connecting" | "open" | "closed";

export interface AssistantSocketCallbacks {
  onOpen?: () => void;
  onEvent: (event: ServerEvent) => void;
  onStatus: (status: WsStatus) => void;
  onError?: (err: Event) => void;
}

/**
 * Thin wrapper around the native WebSocket. One instance per session.
 * No auto-reconnect in Phase 1 — the user retries by pressing Start again.
 */
export class AssistantSocket {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly cb: AssistantSocketCallbacks;

  constructor(url: string, cb: AssistantSocketCallbacks) {
    this.url = url;
    this.cb = cb;
  }

  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;

    this.cb.onStatus("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.cb.onStatus("open");
      this.cb.onOpen?.();
    };

    ws.onclose = () => {
      this.cb.onStatus("closed");
      if (this.ws === ws) this.ws = null;
    };

    ws.onerror = (e) => {
      this.cb.onError?.(e);
    };

    ws.onmessage = (e) => {
      if (typeof e.data !== "string") return;
      try {
        const evt = JSON.parse(e.data) as ServerEvent;
        this.cb.onEvent(evt);
      } catch {
        // malformed event from server — swallow so UI stays alive.
      }
    };
  }

  send(evt: ClientEvent): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(evt));
  }

  sendBinary(buf: ArrayBuffer | Blob): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(buf);
  }

  close(): void {
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close();
  }
}
