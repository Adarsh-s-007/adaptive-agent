import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

function json(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body, headers: new Headers() } as Response;
}

describe("app shell", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
        const path = new URL(input).pathname;
        if (path === "/health") return json({ status: "ok", db: "ok", hindsight: "ok", groq: "down" });
        if (auth !== "Bearer good") return json({ error: { code: "UNAUTHORIZED", message: "Missing or invalid access token." } }, 401);
        if (path === "/api/v1/projects") return json([{ id: "p1", name: "ApexCart", bank_status: "ready" }]);
        if (path === "/api/v1/projects/p1/memories") return json([]);
        return json({ error: { code: "NOT_FOUND", message: "nope" } }, 404);
      }),
    );
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("rejects a bad token, then opens the project frame", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByLabelText("Access token"), "bad");
    await user.click(screen.getByRole("button", { name: "Enter" }));
    expect(await screen.findByText("Missing or invalid access token.")).toBeTruthy();

    await user.clear(screen.getByLabelText("Access token"));
    await user.type(screen.getByLabelText("Access token"), "good");
    await user.click(screen.getByRole("button", { name: "Enter" }));
    await user.selectOptions(await screen.findByLabelText("Project"), "p1");
    expect(await screen.findByRole("link", { name: "Memory" })).toBeTruthy();
    await user.click(screen.getByRole("link", { name: "Memory" }));
    expect(await screen.findByText("No memory yet")).toBeTruthy();
  });
});
