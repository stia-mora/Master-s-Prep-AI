import test from "node:test";
import assert from "node:assert/strict";
import {
  completeNewUserTour,
  getNewUserTourCompletedKey,
  getNewUserTourPendingKey,
  markNewUserTourPending,
  shouldShowNewUserTour,
} from "../lib/onboarding";

class MemoryStorage {
  private values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

const user = {
  user_id: "user_123",
  email: "Student@Example.com",
};

test("new user tour is hidden until registration marks it pending", () => {
  const storage = new MemoryStorage();
  assert.equal(shouldShowNewUserTour(user, storage), false);

  markNewUserTourPending(user, storage);

  assert.equal(storage.getItem(getNewUserTourPendingKey(user)), "1");
  assert.equal(shouldShowNewUserTour(user, storage), true);
});

test("completing the tour records completion and clears pending state", () => {
  const storage = new MemoryStorage();
  markNewUserTourPending(user, storage);

  completeNewUserTour(user, storage);

  assert.equal(storage.getItem(getNewUserTourPendingKey(user)), null);
  assert.equal(storage.getItem(getNewUserTourCompletedKey(user)), "1");
  assert.equal(shouldShowNewUserTour(user, storage), false);
});

test("tour state is isolated per user", () => {
  const storage = new MemoryStorage();
  markNewUserTourPending(user, storage);

  assert.equal(
    shouldShowNewUserTour({ user_id: "user_456", email: "other@example.com" }, storage),
    false,
  );
});
