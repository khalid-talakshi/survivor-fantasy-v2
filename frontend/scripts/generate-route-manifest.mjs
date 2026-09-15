import { writeFileSync } from "node:fs";

const routes = [
  "/", "/sign-in", "/auth/callback", "/set-password", "/app", "/app/admin", "/app/leagues/$leagueId/overview",
  "/app/leagues/$leagueId/roster", "/app/leagues/$leagueId/standings", "/app/leagues/$leagueId/wagers",
  "/app/leagues/$leagueId/admin",
];
writeFileSync("src/routeTree.gen.ts", `/* Generated route manifest. Do not edit. */\nexport const routeManifest = ${JSON.stringify(routes)} as const;\n`);
