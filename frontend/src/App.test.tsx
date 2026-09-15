import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { createRuntime } from "./lib/api";
import { createAuthController } from "./lib/auth";
import { createAppRouter } from "./router";

afterEach(cleanup);

async function renderRoute(path: string) {
  const auth = createAuthController();
  const runtime = createRuntime(auth);
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
});
