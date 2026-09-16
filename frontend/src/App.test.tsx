import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createRuntime } from "./lib/api";
import { createAuthController } from "./lib/auth";
import { createAppRouter } from "./router";

afterEach(cleanup);

async function renderRoute(
  path: string,
  auth = createAuthController(),
  fetch?: typeof globalThis.fetch,
) {
  const runtime = createRuntime(auth, undefined, { baseUrl: "http://localhost", fetch });
  const router = createAppRouter(
    { auth, runtime },
    createMemoryHistory({ initialEntries: [path] }),
  );
  await router.load();
  render(
    <QueryClientProvider client={runtime.queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("routed application", () => {
  it("renders the invitation landing route and navigates to sign-in", async () => {
    const user = userEvent.setup();
    await renderRoute("/");

    expect(screen.getByRole("heading", { name: /your tribe/i })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /sign in with your invitation/i }));
    expect(await screen.findByRole("heading", { name: /welcome back/i })).toBeInTheDocument();
  });

  it("shows a sanitized alert for an unauthorized redirect", async () => {
    await renderRoute("/sign-in?reason=unauthorized");

    expect(await screen.findByRole("alert")).toHaveTextContent(/session ended|invitation could not be verified/i);
  });

  it("ignores unsupported authentication reasons", async () => {
    await renderRoute("/sign-in?reason=provider-secret");

    expect(await screen.findByRole("heading", { name: /welcome back/i })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("surfaces fragment callback failures without exposing provider details", async () => {
    const router = await renderRoute("/auth/callback#error=access_denied&error_code=otp_expired&error_description=Invitation+expired");

    expect(await screen.findByRole("heading", { name: /welcome back/i })).toBeInTheDocument();
    expect(router.state.location.search).toMatchObject({ next: "/app" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/session ended|invitation could not be verified/i);
    expect(screen.queryByText(/invitation expired/i)).not.toBeInTheDocument();
  });

  it("exchanges a valid PKCE invitation code and continues to password setup", async () => {
    const auth = createAuthController();
    const exchangeCodeForSession = vi.spyOn(auth.client.auth, "exchangeCodeForSession").mockResolvedValue({ data: { session: {} }, error: null } as never);
    vi.spyOn(auth, "initialize").mockResolvedValue({ status: "authenticated", session: {} as never });

    await renderRoute("/auth/callback?code=valid-invitation", auth);

    expect(exchangeCodeForSession).toHaveBeenCalledWith("valid-invitation");
    expect(await screen.findByRole("heading", { name: /set your password/i })).toBeInTheDocument();
  });

  it("revalidates confirmation when the password changes", async () => {
    const user = userEvent.setup();
    const auth = createAuthController();
    vi.spyOn(auth, "initialize").mockResolvedValue({ status: "authenticated", session: {} as never });
    const updatePassword = vi.spyOn(auth, "updatePassword");
    await renderRoute("/set-password", auth);

    const password = screen.getByLabelText(/^password$/i);
    const confirmation = screen.getByLabelText(/confirm password/i);
    await user.type(password, "first-password");
    await user.type(confirmation, "first-password");
    await user.clear(password);
    await user.type(password, "second-password");

    expect(await screen.findByText("Passwords must match.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set password/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /set password/i }));
    expect(updatePassword).not.toHaveBeenCalled();
  });

  it("separates completed leagues into read-only history", async () => {
    const auth = createAuthController();
    vi.spyOn(auth, "initialize").mockResolvedValue({ status: "authenticated", session: {} as never });
    const fetch = vi.fn<typeof globalThis.fetch>(async () => new Response(JSON.stringify({
      account: { id: "account", email: "owner@example.com", display_name: "Owner", is_system_owner: true },
      leagues: [
        { id: "active", name: "Current", season_name: "48", state: "active", roster_locked: false, is_commissioner: true, participation_state: "active", read_only: false },
        { id: "completed", name: "Archive", season_name: "47", state: "completed", roster_locked: true, is_commissioner: true, participation_state: "active", read_only: true },
      ],
    }), { headers: { "content-type": "application/json" } }));

    await renderRoute("/app", auth, fetch);

    expect(await screen.findByRole("heading", { name: "Active leagues" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Past seasons" })).toBeInTheDocument();
    expect(screen.getByText("Completed · Read-only")).toBeInTheDocument();
  });

  it("recovers the owner creation form after a network failure", async () => {
    const auth = createAuthController();
    vi.spyOn(auth, "initialize").mockResolvedValue({ status: "authenticated", session: {} as never });
    const fetch = vi.fn<typeof globalThis.fetch>(async (request, init) => {
      if ((request instanceof Request ? request.method : init?.method) === "POST") {
        throw new Error("offline");
      }
      return new Response(JSON.stringify({
        account: { id: "account", email: "owner@example.com", display_name: "Owner", is_system_owner: true },
        leagues: [],
      }), { headers: { "content-type": "application/json" } });
    });

    await renderRoute("/app/admin", auth, fetch);
    fireEvent.change(screen.getByLabelText("League name"), { target: { value: "New league" } });
    fireEvent.change(screen.getByLabelText("Season name"), { target: { value: "48" } });
    fireEvent.submit(screen.getByRole("button", { name: "Create league" }).closest("form")!);

    expect(await screen.findByRole("status")).toHaveTextContent(/check your connection/i);
    expect(screen.getByRole("button", { name: "Create league" })).toBeEnabled();
  });

  it("submits the entered league and season names", async () => {
    const auth = createAuthController();
    vi.spyOn(auth, "initialize").mockResolvedValue({ status: "authenticated", session: {} as never });
    const fetch = vi.fn<typeof globalThis.fetch>(async (request, init) => {
      if ((request instanceof Request ? request.method : init?.method) === "POST") {
        return new Response(JSON.stringify({ id: "new", name: "New league", season_name: "48", state: "active", roster_locked: false, is_commissioner: true, participation_state: "non_playing", read_only: false }), { headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ account: { id: "account", email: "owner@example.com", display_name: "Owner", is_system_owner: true }, leagues: [] }), { headers: { "content-type": "application/json" } });
    });

    await renderRoute("/app/admin", auth, fetch);
    fireEvent.change(screen.getByLabelText("League name"), { target: { value: "New league" } });
    fireEvent.change(screen.getByLabelText("Season name"), { target: { value: "48" } });
    fireEvent.submit(screen.getByRole("button", { name: "Create league" }).closest("form")!);

    expect(await screen.findByRole("status")).toHaveTextContent("Created New league.");
    const postRequest = fetch.mock.calls.find(([request, init]) => (request instanceof Request ? request.method : init?.method) === "POST")?.[0] as Request;
    expect(await postRequest.json()).toEqual({ name: "New league", season_name: "48" });
  });
});
