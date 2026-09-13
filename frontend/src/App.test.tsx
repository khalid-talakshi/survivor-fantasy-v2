import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("presents the invitation entry point", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /your tribe/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with your invitation/i })).toBeInTheDocument();
  });
});

