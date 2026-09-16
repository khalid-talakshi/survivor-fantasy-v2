import { describe, expect, it, vi } from "vitest";
import type { AuthChangeEvent, Session, SupabaseClient } from "@supabase/supabase-js";
import { createAuthController } from "./auth";

function createSupabaseFake(initialSession: Session | null) {
  let session = initialSession;
  let authChange: ((event: AuthChangeEvent, nextSession: Session | null) => void) | undefined;
  const unsubscribe = vi.fn();
  const onAuthStateChange = vi.fn((callback: (event: AuthChangeEvent, nextSession: Session | null) => void) => {
    authChange = callback;
    return { data: { subscription: { unsubscribe } } };
  });
  const getSession = vi.fn(async () => ({ data: { session } }));
  const client = { auth: { onAuthStateChange, getSession } } as unknown as SupabaseClient;

  return {
    client,
    getSession,
    onAuthStateChange,
    unsubscribe,
    emit(event: AuthChangeEvent, nextSession: Session | null) {
      session = nextSession;
      authChange?.(event, nextSession);
    },
  };
}

describe("auth controller", () => {
  it("bootstraps once, subscribes once, and publishes refreshed sessions", async () => {
    const initialSession = { access_token: "initial-token" } as Session;
    const refreshedSession = { access_token: "refreshed-token" } as Session;
    const supabase = createSupabaseFake(initialSession);
    const onChange = vi.fn();
    const auth = createAuthController(supabase.client, onChange);

    const [first, second] = await Promise.all([auth.initialize(), auth.initialize()]);

    expect(supabase.onAuthStateChange).toHaveBeenCalledTimes(1);
    expect(supabase.getSession).toHaveBeenCalledTimes(1);
    expect(first).toEqual({ status: "authenticated", session: initialSession });
    expect(second).toEqual({ status: "authenticated", session: initialSession });

    supabase.emit("TOKEN_REFRESHED", refreshedSession);

    expect(auth.getState()).toEqual({ status: "authenticated", session: refreshedSession });
    expect(onChange).toHaveBeenLastCalledWith({ status: "authenticated", session: refreshedSession });

    auth.dispose();
    expect(supabase.unsubscribe).toHaveBeenCalledOnce();
  });
});
