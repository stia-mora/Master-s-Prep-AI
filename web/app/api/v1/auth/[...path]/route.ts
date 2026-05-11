import { NextRequest, NextResponse } from "next/server";

const RAW_BACKEND_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001").replace(/\/+$/, "");
const BACKEND_BASE = RAW_BACKEND_BASE.endsWith("/api") ? RAW_BACKEND_BASE.slice(0, -4) : RAW_BACKEND_BASE;

type RouteContext = { params: Promise<{ path?: string[] }> };

function appendSetCookies(source: Response, target: NextResponse) {
  const headersWithCookies = source.headers as Headers & { getSetCookie?: () => string[] };
  const cookies = headersWithCookies.getSetCookie?.() || [];
  if (cookies.length > 0) {
    for (const cookie of cookies) target.headers.append("set-cookie", cookie);
    return;
  }
  const cookie = source.headers.get("set-cookie");
  if (cookie) target.headers.append("set-cookie", cookie);
}

async function proxyAuth(request: NextRequest, context: RouteContext) {
  const params = await context.params;
  const path = (params.path || []).join("/");
  const target = BACKEND_BASE + "/api/v1/auth/" + path + request.nextUrl.search;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");

  const response = await fetch(target, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
    cache: "no-store",
    redirect: "manual",
  });

  const responseHeaders = new Headers(response.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("set-cookie");

  const proxied = new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
  appendSetCookies(response, proxied);
  return proxied;
}

export const dynamic = "force-dynamic";
export const GET = proxyAuth;
export const POST = proxyAuth;
export const PATCH = proxyAuth;
export const PUT = proxyAuth;
export const DELETE = proxyAuth;
