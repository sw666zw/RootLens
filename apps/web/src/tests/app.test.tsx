import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../app";
import {
  diagnosisDetail,
  diagnosisSummary,
  explanationDetail,
  explanationSummary,
  incidentDetail,
  incidentSummary,
  response,
  validation,
} from "./fixtures";

function pathOf(input: RequestInfo | URL): string {
  return new URL(String(input), "http://local.test").pathname;
}

function renderPath(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

function defaultFetch(input: RequestInfo | URL): Promise<Response> {
  const path = pathOf(input);
  if (path.endsWith("/health"))
    return Promise.resolve(response({ status: "ok", service: "diagnosis" }));
  if (path.endsWith("/incidents"))
    return Promise.resolve(response([incidentSummary]));
  if (path.endsWith("/diagnoses"))
    return Promise.resolve(response([diagnosisSummary]));
  if (path.endsWith("/explanations"))
    return Promise.resolve(response([explanationSummary]));
  throw new Error(`Unhandled request: ${path}`);
}

describe("application routes and dashboard", () => {
  it("renders application routing and the overview", async () => {
    vi.stubGlobal("fetch", vi.fn(defaultFetch));
    renderPath("/");
    expect(
      screen.getByRole("heading", { name: "System overview" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
  });

  it("keeps dashboard sections independent when one endpoint fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (pathOf(input).endsWith("/diagnoses"))
          return Promise.resolve(
            response({ detail: "Diagnoses unavailable." }, 503),
          );
        return defaultFetch(input);
      }),
    );
    renderPath("/");
    expect(
      (await screen.findAllByText("Diagnoses unavailable.")).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "baseline" })).toBeInTheDocument();
    expect(screen.getByText("Systems appear healthy")).toBeInTheDocument();
  });

  it("shows one section loading while other dashboard data renders", async () => {
    const pendingIncidents = new Promise<Response>(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (pathOf(input).endsWith("/incidents")) return pendingIncidents;
        return defaultFetch(input);
      }),
    );
    renderPath("/");
    expect(
      await screen.findByText("Loading recent incidents…"),
    ).toBeInTheDocument();
    expect(screen.getByText("Systems appear healthy")).toBeInTheDocument();
  });

  it("shows the not-found page for unknown routes", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderPath("/not-a-route");
    expect(
      screen.getByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
  });

  it("uses safe attributes for every external tool link", () => {
    vi.stubGlobal("fetch", vi.fn(defaultFetch));
    renderPath("/");
    for (const name of ["Grafana", "Jaeger", "Prometheus"]) {
      const link = screen.getByRole("link", { name: new RegExp(name) });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noreferrer");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
  });
});

describe("incidents", () => {
  it("does not expose ground-truth fields from an incident list response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          response([
            {
              ...incidentSummary,
              expected_root_cause: "secret",
              expected_symptoms: ["secret"],
              target_service: "inventory",
            },
          ]),
        ),
      ),
    );
    renderPath("/incidents");
    expect(await screen.findByText("baseline")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.queryByText("inventory")).not.toBeInTheDocument();
  });

  it("renders only the safe incident detail projection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response(incidentDetail))),
    );
    renderPath(`/incidents/${incidentSummary.scenario_id}`);
    expect(await screen.findByText("SAFE-SKU")).toBeInTheDocument();
    expect(screen.getByText("Request IDs captured")).toBeInTheDocument();
    expect(screen.queryByText("expected_root_cause")).not.toBeInTheDocument();
  });

  it("submits the diagnosis options, prevents duplicates, and navigates", async () => {
    let resolvePost!: (value: Response) => void;
    const postResult = new Promise<Response>((resolve) => {
      resolvePost = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") return postResult;
      return Promise.resolve(response(incidentDetail));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPath(`/incidents/${incidentSummary.scenario_id}`);
    await screen.findByText("SAFE-SKU");
    await user.click(screen.getByLabelText("Require all telemetry sources"));
    await user.type(screen.getByLabelText(/Window padding/), "20");
    const button = screen.getByRole("button", { name: "Run diagnosis" });
    await user.click(button);
    await user.click(button);
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(1);
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    )!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      require_all_sources: true,
      window_padding_seconds: 20,
    });
    resolvePost(
      response(
        {
          ...diagnosisSummary,
          summary: "Done",
          report_url: `/diagnoses/${diagnosisSummary.diagnosis_id}`,
        },
        201,
      ),
    );
    expect(
      await screen.findByRole("heading", { name: "Diagnosis detail" }),
    ).toBeInTheDocument();
  });
});

describe("diagnoses and explanations", () => {
  it("shows confidence, coverage, grouped evidence, and plain text", async () => {
    const unsafe = "<img src=x onerror=alert(1)>";
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          response({
            ...diagnosisDetail,
            evidence: [{ ...diagnosisDetail.evidence[0], observation: unsafe }],
          }),
        ),
      ),
    );
    renderPath(`/diagnoses/${diagnosisSummary.diagnosis_id}`);
    expect(
      await screen.findByRole("meter", { name: /high confidence/i }),
    ).toHaveAttribute("aria-valuenow", "86");
    expect(
      screen.getByRole("heading", { name: "metrics" }),
    ).toBeInTheDocument();
    expect(screen.getByText(unsafe)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("partial")).toBeInTheDocument();
  });

  it("defaults explanation generation to template", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response(diagnosisDetail))),
    );
    renderPath(`/diagnoses/${diagnosisSummary.diagnosis_id}`);
    expect(await screen.findByLabelText("Provider")).toHaveValue("template");
  });

  it("displays the exact safe OpenAI-disabled response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === "POST"
          ? Promise.resolve(
              response({ detail: "OpenAI explanations are not enabled." }, 503),
            )
          : Promise.resolve(response(diagnosisDetail)),
      ),
    );
    const user = userEvent.setup();
    renderPath(`/diagnoses/${diagnosisSummary.diagnosis_id}`);
    await user.selectOptions(
      await screen.findByLabelText("Provider"),
      "openai",
    );
    await user.click(
      screen.getByRole("button", { name: "Generate explanation" }),
    );
    expect(
      await screen.findByText("OpenAI explanations are not enabled."),
    ).toBeInTheDocument();
  });

  it("navigates after successful explanation generation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST")
          return Promise.resolve(
            response(
              {
                ...explanationSummary,
                executive_summary: "Summary",
                validation,
                warnings: [],
                report_url: `/explanations/${explanationSummary.explanation_id}`,
              },
              201,
            ),
          );
        if (pathOf(input).includes("/explanations/"))
          return Promise.resolve(response(explanationDetail));
        return Promise.resolve(response(diagnosisDetail));
      }),
    );
    const user = userEvent.setup();
    renderPath(`/diagnoses/${diagnosisSummary.diagnosis_id}`);
    await user.click(
      await screen.findByRole("button", { name: "Generate explanation" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Explanation detail" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Explanation generated successfully."),
    ).toBeInTheDocument();
  });

  it("shows claim evidence references and never executes explanation HTML", async () => {
    const unsafe = "<script>window.compromised=true</script>";
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          response({ ...explanationDetail, executive_summary: unsafe }),
        ),
      ),
    );
    renderPath(`/explanations/${explanationSummary.explanation_id}`);
    expect(await screen.findByText(unsafe)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "evidence-001" })).toHaveAttribute(
      "href",
      "#evidence-001",
    );
    expect(document.querySelector("script")).toBeNull();
  });

  it.each([
    [true, 200, "PASS"],
    [false, 422, "FAIL"],
  ])("renders validation %s state", async (overall, status, label) => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === "POST"
          ? Promise.resolve(
              response(
                {
                  ...validation,
                  overall_valid: overall,
                  protected_fields_match: overall,
                  validation_report_id: "validation-test",
                },
                status,
              ),
            )
          : Promise.resolve(response(explanationDetail)),
      ),
    );
    const user = userEvent.setup();
    renderPath(`/explanations/${explanationSummary.explanation_id}`);
    await user.click(
      await screen.findByRole("button", { name: "Validate explanation" }),
    );
    const latest = await screen.findByText("Latest validation");
    await waitFor(() =>
      expect(
        within(latest.parentElement!).getByText(label),
      ).toBeInTheDocument(),
    );
  });
});
