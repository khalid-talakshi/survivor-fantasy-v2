import { describe, expect, it } from "vitest";
import { safeDestination } from "./router";
import { hasAuthCallbackError } from "./lib/auth-callback";

describe("protected destination validation", () => {
  it("keeps same-origin app paths including query and hash", () => {
    expect(safeDestination("/app/leagues/abc?tab=overview#top")).toBe("/app/leagues/abc?tab=overview#top");
  });

  it("rejects open redirects and public destinations", () => {
    expect(safeDestination("https://evil.example/app")).toBe("/app");
    expect(safeDestination("//evil.example/app")).toBe("/app");
    expect(safeDestination("/sign-in")).toBe("/app");
  });
});

describe("Supabase callback errors", () => {
  it("detects the supported error keys in query strings and fragments", () => {
    expect(hasAuthCallbackError("?error=access_denied", "")).toBe(true);
    expect(hasAuthCallbackError("", "#error_code=otp_expired")).toBe(true);
    expect(hasAuthCallbackError("", "#error_description=Invitation+expired")).toBe(true);
  });
});
