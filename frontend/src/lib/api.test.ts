import { describe, expect, it, vi } from "vitest";
import type { Session } from "@supabase/supabase-js";
import type { AuthController } from "./auth";
import { createRuntime } from "./api";

function createAuthFake(initialSession: Session | null) {
  let session = initialSession;
  const getSession = vi.fn(async () => session);
  const signOut = vi.fn(async () => ({ error: null }));
  return {
    auth: { getSession, signOut } as unknown as AuthController,
    setSession(nextSession: Session | null) { session = nextSession; },
    getSession,
    signOut,
  };
}

describe("API runtime", () => {
  it("reads the current token for every request", async () => {
    const auth = createAuthFake({ access_token: "old-token" } as Session);
    const fetch = vi.fn<typeof globalThis.fetch>(async () => new Response(JSON.stringify({}), { headers: { "content-type": "application/json" } }));
    const runtime = createRuntime(auth.auth, undefined, { baseUrl: "http://localhost", fetch });

    await runtime.api.GET("/api/v1/session");
    auth.setSession({ access_token: "new-token" } as Session);
    await runtime.api.GET("/api/v1/session");

    expect(auth.getSession).toHaveBeenCalledTimes(2);
    expect((fetch.mock.calls.at(0)?.[0] as Request).headers.get("Authorization")).toBe("Bearer old-token");
    expect((fetch.mock.calls.at(1)?.[0] as Request).headers.get("Authorization")).toBe("Bearer new-token");
  });

  it("handles concurrent 401 responses once and clears private cached data", async () => {
    const auth = createAuthFake({ access_token: "token" } as Session);
    let finishSignOut!: () => void;
    const signingOut = new Promise<void>((resolve) => { finishSignOut = resolve; });
    auth.signOut.mockImplementation(async () => { await signingOut; return { error: null }; });
    const navigate = vi.fn(async () => undefined);
    const fetch = vi.fn<typeof globalThis.fetch>(async () => new Response(null, { status: 401 }));
    const runtime = createRuntime(auth.auth, navigate, { baseUrl: "http://localhost", fetch });
    runtime.queryClient.setQueryData(["private"], { secret: true });

    const first = runtime.api.GET("/api/v1/session");
    await vi.waitFor(() => expect(auth.signOut).toHaveBeenCalledOnce());
    const second = runtime.api.GET("/api/v1/session");
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await Promise.resolve();
    finishSignOut();
    await Promise.all([first, second]);

    expect(auth.signOut).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledOnce();
    expect(runtime.queryClient.getQueryData(["private"])).toBeUndefined();
  });

  it.each([401, 503])("does not retry status %i", async (status) => {
    const runtime = createRuntime(createAuthFake(null).auth);
    const query = vi.fn(async () => { throw { status }; });

    await expect(runtime.queryClient.fetchQuery({ queryKey: ["session", status], queryFn: query })).rejects.toEqual({ status });

    expect(query).toHaveBeenCalledOnce();
  });
});
