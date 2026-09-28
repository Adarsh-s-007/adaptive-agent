import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./app/App";

const project = {
  id: "01a0e97c-c71f-730d-9d0c-4f0f1db4ba89",
  name: "ApexCart",
  description: "Next.js storefront",
  tech_stack: "Next.js",
  areas: ["auth"],
  bank_id: "pp_apexcart_1234abcd",
  bank_status: "ready",
  memory_mode: "hindsight",
  created_at: new Date().toISOString(),
  stats: { active_records: 13, superseded_records: 0, retracted_records: 0, pending_candidates: 2, active_by_type: { decision: 4 } },
};

function mockFetch() {
  return vi.fn(async (url: string) => {
    const path = String(url);
    let body: unknown = {};
    if (path.endsWith("/api/v1/projects")) body = [project];
    else if (path.endsWith("/api/v1/status")) body = { hindsight: { status: "ok", latency_ms: 40 }, llm: { status: "unconfigured" }, demo_mode: true, force_offline: false, auth_required: false, models: { large: "l", small: "s" } };
    else if (path.includes("/inbox")) body = { groups: [], counts: { pending: 2, filtered: 3, reviewed: 0 } };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ProjectPulse app", () => {
  it("lists projects with their isolated bank and review counts", async () => {
    vi.stubGlobal("fetch", mockFetch());
    renderAt("/");
    expect(await screen.findByText("Launch the ApexCart demo")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("ApexCart").length).toBeGreaterThan(0));
    expect(screen.getByText("pp_apexcart_1234abcd")).toBeTruthy();
  });

  it("shows honest LLM status in the top bar", async () => {
    vi.stubGlobal("fetch", mockFetch());
    renderAt("/");
    expect(await screen.findByText(/LLM: not configured/)).toBeTruthy();
    expect(await screen.findByText(/Hindsight: ready/)).toBeTruthy();
  });
});
