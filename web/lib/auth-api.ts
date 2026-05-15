export interface AuthUser {
  user_id: string;
  email: string;
  display_name: string;
  role: string;
}

export async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getBootstrap(): Promise<{ has_users: boolean }> {
  return authRequest<{ has_users: boolean }>("/api/v1/auth/bootstrap");
}

export function getMe(): Promise<{ user: AuthUser }> {
  return authRequest<{ user: AuthUser }>("/api/v1/auth/me");
}

export function login(email: string, password: string): Promise<{ user: AuthUser }> {
  return authRequest<{ user: AuthUser }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(input: { email: string; password: string; display_name?: string }): Promise<{ user: AuthUser }> {
  return authRequest<{ user: AuthUser }>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function registerFirstAdmin(input: { email: string; password: string; display_name?: string }): Promise<{ user: AuthUser }> {
  return authRequest<{ user: AuthUser }>("/api/v1/auth/register-first-admin", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return authRequest<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });
}