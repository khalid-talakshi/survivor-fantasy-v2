import { createClient, type AuthChangeEvent, type Session, type SupabaseClient } from "@supabase/supabase-js";

export type AuthState = { status: "initializing"; session: null } | { status: "authenticated"; session: Session } | { status: "anonymous"; session: null };
export type AuthController = ReturnType<typeof createAuthController>;

const configuredUrl = import.meta.env.VITE_SUPABASE_URL;
const configuredKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
if (import.meta.env.MODE === "production" && (!configuredUrl || !configuredKey)) throw new Error("Supabase authentication is not configured.");
if (configuredUrl) { const parsedUrl = new URL(configuredUrl); if (parsedUrl.protocol !== "https:" && import.meta.env.MODE === "production") throw new Error("Supabase URL must use HTTPS."); }
export const supabase = createClient(configuredUrl ?? "http://localhost:54321", configuredKey ?? "test-publishable-key");

export function createAuthController(client: SupabaseClient = supabase, onChange?: (state: AuthState) => void) {
  let state: AuthState = { status: "initializing", session: null };
  let initialization: Promise<void> | undefined;
  let unsubscribe: (() => void) | undefined;
  let listener = onChange;

  const publish = (next: AuthState) => { state = next; listener?.(next); };
  const handleChange = (_event: AuthChangeEvent, session: Session | null) => publish(session ? { status: "authenticated", session } : { status: "anonymous", session: null });
  const initialize = async (): Promise<AuthState> => {
    if (initialization) { await initialization; return state; }
    initialization = (async () => {
      if (!unsubscribe) {
        const result = client.auth.onAuthStateChange(handleChange);
        unsubscribe = result.data.subscription.unsubscribe;
      }
      const { data } = await client.auth.getSession();
      const next = data.session ? { status: "authenticated" as const, session: data.session } : { status: "anonymous" as const, session: null };
      publish(next);
    })();
    await initialization;
    return state;
  };
  return {
    initialize,
    getState: () => state,
    getSession: async () => (await client.auth.getSession()).data.session,
    signIn: (email: string, password: string) => client.auth.signInWithPassword({ email, password }),
    updatePassword: (password: string) => client.auth.updateUser({ password }),
    signOut: () => client.auth.signOut(),
    client,
    setOnChange: (next: (state: AuthState) => void) => { listener = next; },
    dispose: () => { unsubscribe?.(); unsubscribe = undefined; initialization = undefined; }
  };
}
