import { useEffect } from "react";

// Host <-> iframe message protocol. The host overlay (home-app
// Overlays/useMessageChannelBroker + utils.ts) transfers a MessagePort to this
// iframe on load via `postMessage({type: INIT_CHANNEL}, origin, [port])`; we
// post CLOSE_MODAL / RESIZE back through that port.
const INIT_CHANNEL = "INIT_CHANNEL";
const CLOSE_MODAL = "CLOSE_MODAL";
const RESIZE = "RESIZE";

let hostPort: MessagePort | null = null;
const queued: unknown[] = [];

if (typeof window !== "undefined") {
  window.addEventListener("message", (event: MessageEvent) => {
    if (event.data?.type === INIT_CHANNEL && event.ports?.[0]) {
      hostPort = event.ports[0];
      // Flush anything posted before the port arrived (e.g. the first resize).
      queued.splice(0).forEach((message) => hostPort?.postMessage(message));
    }
  });
}

function postToHost(message: unknown): void {
  if (hostPort) {
    hostPort.postMessage(message);
  } else {
    queued.push(message);
  }
}

/** Ask the host overlay to close this modal. */
export function closeModal(): void {
  postToHost({ type: CLOSE_MODAL });
}

/** Report the document height to the host so the overlay sizes to its content. */
export function useAutoResize(): void {
  useEffect(() => {
    const report = () => {
      postToHost({ type: RESIZE, height: document.documentElement.scrollHeight });
    };
    report();
    const observer = new ResizeObserver(report);
    observer.observe(document.documentElement);
    return () => observer.disconnect();
  }, []);
}
