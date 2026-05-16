import type { AuthUser } from "./auth-api";

export const NEW_USER_TOUR_VERSION = "2026-05";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const STORAGE_PREFIX = "master_prep_ai:new-user-tour";

function getBrowserStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function getNewUserTourUserKey(user: Pick<AuthUser, "user_id" | "email">): string {
  const raw = user.user_id || user.email.trim().toLowerCase();
  return encodeURIComponent(raw);
}

export function getNewUserTourPendingKey(user: Pick<AuthUser, "user_id" | "email">): string {
  return `${STORAGE_PREFIX}:pending:${getNewUserTourUserKey(user)}`;
}

export function getNewUserTourCompletedKey(user: Pick<AuthUser, "user_id" | "email">): string {
  return `${STORAGE_PREFIX}:completed:${NEW_USER_TOUR_VERSION}:${getNewUserTourUserKey(user)}`;
}

export function markNewUserTourPending(
  user: Pick<AuthUser, "user_id" | "email">,
  storage = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(getNewUserTourPendingKey(user), "1");
  } catch {
    // localStorage can be unavailable in private or locked-down browser contexts.
  }
}

export function shouldShowNewUserTour(
  user: Pick<AuthUser, "user_id" | "email">,
  storage = getBrowserStorage(),
): boolean {
  if (!storage) return false;
  try {
    return (
      storage.getItem(getNewUserTourPendingKey(user)) === "1" &&
      storage.getItem(getNewUserTourCompletedKey(user)) !== "1"
    );
  } catch {
    return false;
  }
}

export function completeNewUserTour(
  user: Pick<AuthUser, "user_id" | "email">,
  storage = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(getNewUserTourCompletedKey(user), "1");
    storage.removeItem(getNewUserTourPendingKey(user));
  } catch {
    // Keep the UI usable even if persistence fails.
  }
}
