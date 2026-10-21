import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Leads from "./Leads";
import SearchRun from "./SearchRun";
import Advisor from "./Advisor";
import LeadDetail from "./LeadDetail";

import App from "../../App";
import {
  type Config,
  type CRMLead,
  type Workspace,
  type Campaign,
  api,
} from "../../services/workspaceApi";

vi.mock("../../services/workspaceApi", async () => ({
  ...(await vi.importActual("../../services/workspaceApi")),
  api: vi.fn(),
}));
const profile = {
  company_name: "",
  website: "",
  offer: "",
  ideal_customer: "",
  deal_size: "",
  geography: "",
  exclusions: "",
  buyer_roles: "",
};
const lead = (id: string, result: string): CRMLead => ({
  id,
  company: id === "a" ? "Acme Clinic" : "Birch Studio",
  domain: id + ".com",
  industry: "Healthcare",
  location: "Austin",
  website: "https://" + id + ".com",
  category: ["valid", "catchall", "unknown"].includes(result)
    ? "verified"
    : "needs_review",
  stage: "new",
  tags: [],
  notes: "",
  next_action: "",
  follow_up: "",
  campaign_ids: [],
  source: "google_maps",
  created_at: "2026-10-16T12:00:00Z",
  updated_at: "2026-10-16T12:00:00Z",
  activities: [],
  assessment: {
    fit: "unknown",
    summary: "Research pending",
    reasons: [],
    unknowns: [],
    evidence: [],
    excluded: false,
  },
  lead: {
    verified: ["valid", "catchall", "unknown"].includes(result),
    contact: {
      first_name: "Pat",
      last_name: "Owner",
      job_title: "Owner",
      email: id + "@company.com",
      phone: null,
      linkedin: null,
      confidence: 90,
    },
    verification: {
      result,
      flags: [],
    },
    business: { business_phone: null },
    enrichment_timestamp: null,
    failure_reason: null,
    contact_scope: null,
    contact_type: "decision_maker",
    google_maps_rank: null,
    filter_reason: null,
  },
});
const workspace: Workspace = {
  profile,
  campaigns: [],
  leads: [lead("a", "valid"), lead("b", "catchall")],
  threads: [],
  account: { email: null, storage: "local" },
};
const config: Config = {
  auth: { url: "", publishable_key: "", local_enabled: true },
  integrations: [],
  sources: [
    {
      id: "google_maps",
      name: "Google Maps",
      provider: "Apify",
      available: true,
      description: "",
      fields: [],
      limits: "",
    },
    {
      id: "company_websites",
      name: "Company websites",
      provider: "Research",
      available: true,
      description: "",
      fields: [],
      limits: "",
    },
  ],
};

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.mocked(api).mockReset();
});
const campaign: Campaign = {
  id: "search1",
  version: 1,
  status: "shortfall",
  created_at: "2026-10-16",
  updated_at: "2026-10-16",
  plan: {
    name: "Texas dentists",
    source: "google_maps",
    niche: "dentists",
    city: "Austin",
    state: "Texas",
    locations: [
      { city: "Austin", state: "Texas" },
      { city: "Round Rock", state: "Texas" },
      { city: "Cedar Park", state: "Texas" },
    ],
    query: "",
    websites: [],
    max_leads: 100,
    rationale: "SEO prospects",
    qualification_criteria: [],
    exclusions: [],
    research_websites: false,
    min_google_maps_rank: null,
    max_google_maps_rank: null,
  },
  message:
    "Found 30 of 100 requested leads across 3 searched locations. 70 more leads are needed.",
  shortfall: 70,
  progress: {
    target: 100,
    discovered: 210,
    processed: 210,
    verified: 30,
    review: 0,
    excluded: 0,
    reused: 0,
  },
  warnings: [],
  events: [],
  usage: { requests: 0, input_tokens: 0, output_tokens: 0 },
  recommendations: [
    {
      city: "Georgetown",
      state: "Texas",
      reason: "Nearby dental businesses suitable for local SEO.",
      evidence: [
        {
          url: "https://example.com/cities",
          title: "City evidence",
          observation: "Nearby market",
        },
      ],
    },
  ],
};

describe("Focused lead workspace", () => {
  it("shows search depth, repeated city passes and the exact email policy", () => {
    render(<SearchRun campaign={{...campaign, status: "enriching",
      plan: {...campaign.plan, email_policy: "valid_only", max_city_rounds: 3},
      locations: [{city: "Austin", state: "Texas", round: 2, business_limit: 140,
        status: "enriching", discovered: 140, processed: 80, leads: 30}]}}
      refresh={vi.fn()} viewLeads={vi.fn()} suggest={vi.fn()} />);
    expect(screen.getByText(/up to 3 passes/)).toBeInTheDocument();
    expect(screen.getByText(/Austin, Texas · Pass 2/)).toBeInTheDocument();
    expect(screen.getByText(/Only NeverBounce valid emails count/)).toBeInTheDocument();
  });
  it("explains provider exhaustion without claiming the target was reached", () => {
    render(<SearchRun campaign={{...campaign, status: "failed", stop_reason: "hunter_quota_exhausted"}}
      refresh={vi.fn()} viewLeads={vi.fn()} suggest={vi.fn()} />);
    expect(screen.getByText("Hunter credits or usage allowance are exhausted.")).toBeInTheDocument();
    expect(screen.getByText("Search interrupted")).toBeInTheDocument();
    expect(screen.queryByText("Target reached")).not.toBeInTheDocument();
  });
  it("opens the agent and exposes only advisor and lead database navigation", async () => {
    window.location.hash = "overview";
    vi.mocked(api).mockImplementation(async (path) =>
      path === "/config" ? config : workspace,
    );
    render(<App />);
    expect(
      await screen.findByRole("textbox", { name: "Message research advisor" }),
    ).toBeInTheDocument();
    for (const name of [
      "Overview",
      "Pipeline",
      "Campaigns",
      "Business profile",
      "Sources & integrations",
      "New campaign",
    ]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    fireEvent.change(
      screen.getByRole("textbox", { name: "Message research advisor" }),
      { target: { value: "Fetch 50 leads" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Lead database 2" }));
    expect(
      screen.getByRole("heading", { name: "Lead database 2" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Research advisor" }));
    expect(
      screen.getByRole("textbox", { name: "Message research advisor" }),
    ).toHaveValue("Fetch 50 leads");
  });
  it("filters the exact accepted verification statuses and displays contact emails", () => {
    render(
      <Leads
        workspace={workspace}
        refresh={vi.fn()}
        openLead={vi.fn()}
        onResearch={vi.fn()}
      />,
    );
    expect(screen.getByText("a@company.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Catch-all 1" }));
    expect(screen.queryByText("Acme Clinic")).not.toBeInTheDocument();
    expect(screen.getByText("Birch Studio")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search leads"), {
      target: { value: "missing" },
    });
    expect(
      screen.getByText("No leads match these filters"),
    ).toBeInTheDocument();
  });
  it("reports the real shortfall and lets the user compose additional cities without starting them", () => {
    const suggest = vi.fn();
    render(
      <SearchRun
        campaign={campaign}
        refresh={vi.fn()}
        viewLeads={vi.fn()}
        suggest={suggest}
      />,
    );
    expect(screen.getByText(/Found 30 of 100/)).toBeInTheDocument();
    expect(screen.getByText("Georgetown, Texas")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "30");
    fireEvent.click(screen.getByRole("button", { name: /Use these cities/ }));
    expect(suggest).toHaveBeenCalledWith(
      expect.stringContaining("Find 70 more leads"),
    );
    expect(suggest).toHaveBeenCalledWith(
      expect.stringContaining("Georgetown, Texas"),
    );
    expect(api).not.toHaveBeenCalled();
  });
  it("can stop a running search inside the advisor", async () => {
    vi.mocked(api).mockResolvedValue({ requested: true });
    render(
      <SearchRun
        campaign={{ ...campaign, status: "enriching", recommendations: [] }}
        refresh={vi.fn().mockResolvedValue(undefined)}
        viewLeads={vi.fn()}
        suggest={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop search" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/campaigns/search1/cancel",
        "POST",
        undefined,
      ),
    );
    expect(
      screen.getByRole("button", { name: "Stop requested" }),
    ).toBeDisabled();
  });
  it("sends a lead request directly through the conversation", async () => {
    const thread = {
      id: "thread1",
      title: "Texas",
      messages: [],
      campaign_ids: [],
      status: "idle",
      usage: { requests: 0, input_tokens: 0, output_tokens: 0 },
    };
    vi.mocked(api).mockResolvedValue(thread);
    render(
      <Advisor
        workspace={workspace}
        refresh={vi.fn().mockResolvedValue(undefined)}
        review={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Message research advisor"), {
      target: { value: "Fetch 50 dentist leads in Austin, Texas" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/threads/thread1/messages",
        "POST",
        expect.objectContaining({
          message: "Fetch 50 dentist leads in Austin, Texas",
        }),
      ),
    );
    expect(
      screen.queryByRole("button", { name: /Confirm|Approve/ }),
    ).not.toBeInTheDocument();
  });
  it("allows an unknown contact under the policy and saves CRM notes", async () => {
    vi.mocked(api).mockResolvedValue({});
    render(
      <LeadDetail
        lead={lead("b", "unknown")}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(
      screen.getByRole("option", { name: "Qualified" }),
    ).not.toBeDisabled();
    expect(
      screen.getByText(/Catch-all and unknown do not confirm deliverability/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Notes"), {
      target: { value: "SEO opportunity" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/leads/b",
        "PATCH",
        expect.objectContaining({ notes: "SEO opportunity" }),
      ),
    );
  });
});
