import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { RouterProvider } from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { createAppRouter } from "./router";
import { createAuthController } from "./lib/auth";
import { createRuntime } from "./lib/api";
import { rememberUnauthorizedReason } from "./lib/auth-callback";

const auth = createAuthController();
const routerRef: { current?: ReturnType<typeof createAppRouter> } = {};
const runtime = createRuntime(auth, async () => {
  rememberUnauthorizedReason();
  await routerRef.current?.navigate({ to: "/sign-in", search: { reason: "unauthorized", next: "/app" } });
});
const router = createAppRouter({ auth, runtime });
routerRef.current = router;
auth.setOnChange((state) => { if (state.status === "anonymous") runtime.queryClient.clear(); else void runtime.queryClient.invalidateQueries({ queryKey: ["session"] }); void router.invalidate(); });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={runtime.queryClient}><RouterProvider router={router} /></QueryClientProvider>
  </StrictMode>
);
