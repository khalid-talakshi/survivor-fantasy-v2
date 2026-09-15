import { describe, expect, it } from "vitest";
import { safeDestination } from "./router";

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
