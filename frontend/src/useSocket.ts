import { useEffect, useRef, useState } from "react";

export type SocketStatus = "connecting" | "open" | "reconnecting";

function socketUrl(path: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${path}`;
}

/**
 * Subscribes to a backend WebSocket and reconnects forever.
 *
 * `onMessage` is called for every message. The status turns to "reconnecting"
 * within a second of the link dropping, so the screen never keeps presenting the
 * last numbers as if they were live.
 */
export function useSocket<T>(path: string, onMessage: (message: T) => void): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      socket = new WebSocket(socketUrl(path));
      socket.onopen = () => setStatus("open");
      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(event.data) as T);
        } catch {
          // A malformed message is dropped; the next one arrives within 200 ms.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        retry = setTimeout(connect, 1000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [path]);

  return status;
}
