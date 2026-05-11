// API configuration and utility functions

// Get API base URL from environment variable.
// The launcher injects NEXT_PUBLIC_API_BASE from the canonical project-root `.env`.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE ||
  (() => {
    if (typeof window !== "undefined") {
      console.error("NEXT_PUBLIC_API_BASE is not set.");
      console.error(
        "Please configure NEXT_PUBLIC_API_BASE in your environment and restart the application.",
      );
      console.error(
        "Run python scripts/start_tour.py to rebuild your local setup if needed.",
      );
    }
    throw new Error(
      "NEXT_PUBLIC_API_BASE is not configured. Please set it in your environment and restart.",
    );
  })();

// Hostnames that always refer to the local machine. When the build-time base
// URL points to one of these, but the page is opened from a non-local origin,
// we rewrite the hostname so requests reach the actual server.
const LOOPBACK_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "::1",
  "[::1]",
]);

let warnedAboutHostSwap = false;

function isLoopbackHost(host: string): boolean {
  return LOOPBACK_HOSTS.has(host.toLowerCase());
}

/**
 * Resolve the effective API base URL at runtime.
 *
 * NEXT_PUBLIC_API_BASE is a build-time constant that is typically set to
 * http://localhost:<port>.  When another machine on the LAN opens the app that
 * constant still points at "localhost", which the remote browser resolves to
 * its *own* loopback address instead of the server.  We detect this situation
 * and swap the hostname for window.location.hostname so the request reaches
 * the actual server regardless of which machine opened the page.
 *
 * The full path/search is preserved (so deployments behind a reverse proxy
 * like `http://localhost:8001/api` continue to work after the rewrite).
 */
export function resolveBase(): string {
  const base = API_BASE_URL;
  if (typeof window === "undefined") return base;
  try {
    const url = new URL(base);
    const clientHost = window.location.hostname;
    if (isLoopbackHost(url.hostname) && !isLoopbackHost(clientHost)) {
      url.hostname = clientHost;
      if (!warnedAboutHostSwap) {
        warnedAboutHostSwap = true;
        console.warn(
          `[api] NEXT_PUBLIC_API_BASE points to "${base}" but the page is served from "${clientHost}"; ` +
            `routing API/WebSocket calls to "${url.toString()}" instead.`,
        );
      }
      // Use href (full URL) instead of origin so we keep any path/search.
      return url.toString().replace(/\/+$/, "");
    }
  } catch {
    // base is not a valid absolute URL – return as-is
  }
  return base;
}

/**
 * Construct a full API URL from a path
 * @param path - API path (e.g., '/api/v1/knowledge/list')
 * @returns Full URL (e.g., 'http://localhost:8001/api/v1/knowledge/list')
 */
export function apiUrl(path: string): string {
  // Remove leading slash if present to avoid double slashes
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Browser requests go through the Next.js same-origin proxy so auth cookies
  // are handled consistently before the proxy forwards to the FastAPI backend.
  if (typeof window !== "undefined" && normalizedPath.startsWith("/api/")) {
    return normalizedPath;
  }

  // Remove trailing slash from base URL if present
  const base = resolveBase();
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;

  return `${normalizedBase}${normalizedPath}`;
}

/**
 * Construct a WebSocket URL from a path
 * @param path - WebSocket path (e.g., '/api/v1/solve')
 * @returns WebSocket URL (e.g., 'ws://localhost:8001/api/v1/ws')
 */
export function wsUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Browser WebSocket requests use the same-origin Next.js rewrite, matching
  // the REST proxy path so auth cookies stay on one origin during local dev.
  if (typeof window !== "undefined" && normalizedPath.startsWith("/api/")) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || window.location.hostname;
    return `${protocol}//${host}${normalizedPath}`;
  }

  // Security Hardening: Convert http to ws and https to wss.
  // In production environments (where API_BASE_URL starts with https), this ensures secure websockets.
  const base = resolveBase()
    .replace(/^http:/, "ws:")
    .replace(/^https:/, "wss:");

  // Remove trailing slash from base URL if present
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;

  return `${normalizedBase}${normalizedPath}`;
}
