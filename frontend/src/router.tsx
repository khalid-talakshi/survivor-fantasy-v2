import { createRootRouteWithContext, createRoute, createRouter, redirect, useRouteContext, useRouter } from "@tanstack/react-router";
import { Outlet } from "@tanstack/react-router";
import { AppShell, Callback, ComingSoon, Landing, LeagueHome, LeaguePage, SetPassword, SignIn, StatePage } from "./App";
import type { AuthController } from "./lib/auth";
import type { ApiRuntime } from "./lib/api";
import { sessionQueryOptions } from "./lib/session";

export type RouterContext = { auth: AuthController; runtime: ApiRuntime };
export function useApp() { const context = useRouteContext({ from: "__root__" }); const router = useRouter(); return { ...context, queryClient: context.runtime.queryClient, api: context.runtime.api, router }; }
export function safeDestination(value: unknown): string { if (typeof value !== "string" || !(value === "/app" || value.startsWith("/app/")) || value.startsWith("//")) return "/app"; try { const url = new URL(value, window.location.origin); return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : "/app"; } catch { return "/app"; } }

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: () => <Outlet /> });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Landing });
const signInRoute = createRoute({ getParentRoute: () => rootRoute, path: "/sign-in", validateSearch: (search) => ({ next: safeDestination(search.next), reason: typeof search.reason === "string" ? search.reason : undefined }), component: SignIn });
const callbackRoute = createRoute({ getParentRoute: () => rootRoute, path: "/auth/callback", component: Callback });
const setPasswordRoute = createRoute({ getParentRoute: () => rootRoute, path: "/set-password", beforeLoad: async ({ context }) => { const state = await context.auth.initialize(); if (state.status !== "authenticated") throw redirect({ to: "/sign-in", search: { next: "/set-password" } }); }, component: SetPassword });
const appRoute = createRoute({ getParentRoute: () => rootRoute, path: "/app", beforeLoad: async ({ context, location }) => { const state = await context.auth.initialize(); if (state.status !== "authenticated") { const next = safeDestination(location.href); sessionStorage.setItem("sf:next", next); throw redirect({ to: "/sign-in", search: { next } }); } }, loader: ({ context }) => context.runtime.queryClient.ensureQueryData(sessionQueryOptions(context.runtime.api)), pendingComponent: () => <StatePage title="Loading your leagues…" />, errorComponent: ({ error, reset }) => <section className="state-page"><h1>{(error as { status?: number }).status === 503 ? "Service unavailable" : "We couldn’t load your account."}</h1><p>{(error as { status?: number }).status === 503 ? "The league service is temporarily unavailable." : "Check your connection and try again."}</p><button type="button" onClick={reset}>Try again</button></section>, component: AppShell });
const appIndexRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: LeagueHome });
const ensureSession = (context: RouterContext) => context.runtime.queryClient.ensureQueryData(sessionQueryOptions(context.runtime.api));
const systemAdminRoute = createRoute({ getParentRoute: () => appRoute, path: "/admin", beforeLoad: async ({ context }) => { const session = await ensureSession(context); if (!session.account.is_system_owner) throw redirect({ to: "/app" }); }, component: ComingSoon });
const leagueRoute = createRoute({ getParentRoute: () => appRoute, path: "/leagues/$leagueId", beforeLoad: async ({ context, params }) => { const session = await ensureSession(context); if (!session.leagues.some((league) => league.id === params.leagueId)) throw redirect({ to: "/app" }); }, component: LeaguePage });
const overviewRoute = createRoute({ getParentRoute: () => leagueRoute, path: "/overview", component: ComingSoon });
const rosterRoute = createRoute({ getParentRoute: () => leagueRoute, path: "/roster", component: ComingSoon });
const standingsRoute = createRoute({ getParentRoute: () => leagueRoute, path: "/standings", component: ComingSoon });
const wagersRoute = createRoute({ getParentRoute: () => leagueRoute, path: "/wagers", component: ComingSoon });
const adminRoute = createRoute({ getParentRoute: () => leagueRoute, path: "/admin", beforeLoad: async ({ context, params }) => { const session = await ensureSession(context); if (!session.leagues.find((league) => league.id === params.leagueId)?.is_commissioner) throw redirect({ to: "/app" }); }, component: ComingSoon });
const routeTree = rootRoute.addChildren([indexRoute, signInRoute, callbackRoute, setPasswordRoute, appRoute.addChildren([appIndexRoute, systemAdminRoute, leagueRoute.addChildren([overviewRoute, rosterRoute, standingsRoute, wagersRoute, adminRoute])])]);
export function createAppRouter(context: RouterContext) { return createRouter({ routeTree, context, defaultPreload: "intent" }); }
