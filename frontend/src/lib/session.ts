import { queryOptions } from "@tanstack/react-query";
import type { paths, components } from "./api.generated";
import type createClient from "openapi-fetch";

type Api = ReturnType<typeof createClient<paths>>;
export type SessionResponse = components["schemas"]["SessionResponse"];

export const sessionQueryOptions = (api: Api) => queryOptions({
  queryKey: ["session"],
  queryFn: async (): Promise<SessionResponse> => {
    const result = await api.GET("/api/v1/session");
    if (result.error || !result.data) {
      const detail = result.error as { error?: { message?: string } } | undefined;
      throw Object.assign(new Error(detail?.error?.message ?? "The session request failed."), { status: result.response.status });
    }
    return result.data;
  },
  retry: false,
  staleTime: 30_000
});
