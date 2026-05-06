import test from "node:test";
import assert from "node:assert/strict";

// Must be set before importing the module under test, since API_BASE_URL is
// read at module-load time and the module throws if it's missing.
process.env.NEXT_PUBLIC_API_BASE = "http://localhost:8001/api";

let apiModulePromise: Promise<typeof import("../lib/api")> | null = null;

async function loadApiModule(): Promise<typeof import("../lib/api")> {
  apiModulePromise ??= import("../lib/api");
  return apiModulePromise;
}

function setWindow(hostname: string | undefined, protocol = "http:", host?: string): void {
  if (hostname === undefined) {
    delete (globalThis as { window?: unknown }).window;
    return;
  }
  (globalThis as { window?: unknown }).window = {
    location: { hostname, protocol, host: host ?? hostname },
  } as unknown;
}

test("resolveBase returns the build-time base in SSR (no window)", async () => {
  const { resolveBase } = await loadApiModule();
  setWindow(undefined);
  assert.equal(resolveBase(), "http://localhost:8001/api");
});

test("resolveBase returns base unchanged when client is also on localhost", async () => {
  const { resolveBase } = await loadApiModule();
  setWindow("localhost", "http:", "localhost:3000");
  assert.equal(resolveBase(), "http://localhost:8001/api");
});

test("resolveBase rewrites loopback hostname to remote LAN host and preserves path", async () => {
  const { resolveBase } = await loadApiModule();
  setWindow("192.168.1.10", "http:", "192.168.1.10:3000");
  assert.equal(resolveBase(), "http://192.168.1.10:8001/api");
});

test("resolveBase treats IPv6 loopback as loopback (no swap when client is also ::1)", async () => {
  const { resolveBase } = await loadApiModule();
  setWindow("::1", "http:", "[::1]:3000");
  assert.equal(resolveBase(), "http://localhost:8001/api");
});

test("apiUrl uses the same-origin proxy in the browser", async () => {
  const { apiUrl } = await loadApiModule();
  setWindow("10.0.0.5", "http:", "10.0.0.5:3000");
  assert.equal(apiUrl("/api/v1/knowledge/list"), "/api/v1/knowledge/list");
});

test("apiUrl composes full backend URLs during SSR", async () => {
  const { apiUrl } = await loadApiModule();
  setWindow(undefined);
  assert.equal(
    apiUrl("/api/v1/knowledge/list"),
    "http://localhost:8001/api/api/v1/knowledge/list",
  );
});

test("wsUrl uses the same-origin proxy in the browser", async () => {
  const { wsUrl } = await loadApiModule();
  setWindow("10.0.0.5", "http:", "10.0.0.5:3000");
  assert.equal(wsUrl("/api/v1/ws"), "ws://10.0.0.5:3000/api/v1/ws");
});

test("wsUrl uses secure same-origin websocket on HTTPS pages", async () => {
  const { wsUrl } = await loadApiModule();
  setWindow("app.example.com", "https:", "app.example.com");
  assert.equal(wsUrl("/api/v1/ws"), "wss://app.example.com/api/v1/ws");
});

test("wsUrl composes full backend URLs during SSR", async () => {
  const { wsUrl } = await loadApiModule();
  setWindow(undefined);
  assert.equal(wsUrl("/api/v1/ws"), "ws://localhost:8001/api/api/v1/ws");
});