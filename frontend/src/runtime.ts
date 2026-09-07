import { configureRuntime } from "./api";

type DesktopSession = { base_url: string; token: string };

const pause = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function waitForBackend(session: DesktopSession) {
  const healthUrl = `${session.base_url.replace(/\/$/, "")}/api/health`;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(healthUrl, { headers: { Authorization: `Bearer ${session.token}` } });
      if (response.ok) return;
    } catch {
      // The sidecar may need a moment to bind its local port.
    }
    await pause(250);
  }
}

/**
 * Browser development uses Vite's proxy. A packaged Tauri window asks the
 * Rust shell for the private sidecar session and waits until it is ready.
 */
export const runtimeReady: Promise<void> = (async () => {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const session = await invoke<DesktopSession>("get_backend_session");
    configureRuntime(session.base_url, session.token);
    await waitForBackend(session);
  } catch {
    // Running in an ordinary browser: keep the Vite proxy configuration.
  }
})();
