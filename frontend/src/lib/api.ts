import createClient from "openapi-fetch";
import type { paths } from "./api.generated";
import type { AuthController } from "./auth";
import { QueryClient } from "@tanstack/react-query";
export type ApiRuntime = { queryClient: QueryClient; api: ReturnType<typeof createClient<paths>> };

export function createApiClient(options: { getAccessToken: () => Promise<string | null>; onUnauthorized: () => Promise<void> }) {
  let unauthorized: Promise<void> | undefined;
  const client = createClient<paths>({ baseUrl: "" });
  client.use({
    async onRequest({ request }) {
      const token = await options.getAccessToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
    async onResponse({ response }) {
      if (response.status === 401) {
        unauthorized ??= options.onUnauthorized().finally(() => { unauthorized = undefined; });
        await unauthorized;
      }
      return response;
    }
  });
  return client;
}

export function createRuntime(auth: AuthController, onUnauthorizedNavigate?: () => Promise<void>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: (count, error: unknown) => count < 1 && (error as { status?: number }).status !== 401 && (error as { status?: number }).status !== 503 } } });
  const api = createApiClient({
    getAccessToken: async () => (await auth.getSession())?.access_token ?? null,
    onUnauthorized: async () => { await queryClient.cancelQueries(); queryClient.clear(); await auth.signOut(); await onUnauthorizedNavigate?.(); }
  });
  return { queryClient, api };
}
