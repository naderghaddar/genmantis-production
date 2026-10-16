import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Leads from "./Leads";
import CampaignForm from "./CampaignForm";
import LeadDetail from "./LeadDetail";
import { BusinessSettings } from "./Settings";
import App from "../../App";
import {
  type Config,
  type CRMLead,
  type Workspace,
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
const lead = (id: string, category: CRMLead["category"]): CRMLead => ({
  id,
  company: id === "a" ? "Acme Clinic" : "Birch Studio",
  domain: id + ".com",
  industry: "Healthcare",
  location: "Austin",
  website: "https://" + id + ".com",
  category,
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
    verified: category === "verified",
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
      result: category === "verified" ? "valid" : "catchall",
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
  leads: [lead("a", "verified"), lead("b", "needs_review")],
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
describe("Lead workspace", () => {
  it("loads the workspace and navigates the research, CRM and pipeline screens", async () => {
    window.location.hash = "overview";
    vi.mocked(api).mockImplementation(async (path) => path === "/config" ? config : workspace);
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Good (morning|afternoon|evening)/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Research advisor AI" }));
    expect(screen.getByRole("textbox", { name: "Message research advisor" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lead database 2" }));
    expect(screen.getByRole("heading", { name: "Lead database 2" })).toBeInTheDocument();
    expect(screen.getByText("Acme Clinic")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pipeline" }));
    expect(screen.getByRole("heading", { name: "Your pipeline" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Business profile" }));
    expect(screen.getByLabelText("What do you sell?")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/config");
    expect(api).toHaveBeenCalledWith("");
  });
  it("filters verification categories and company search without conflating fit", () => {
    render(
      <Leads
        workspace={workspace}
        refresh={vi.fn()}
        openLead={vi.fn()}
        onResearch={vi.fn()}
      />,
    );
    expect(screen.getByText("Acme Clinic")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Needs review 1" }));
    expect(screen.queryByText("Acme Clinic")).not.toBeInTheDocument();
    expect(screen.getByText("Birch Studio")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search leads"), {
      target: { value: "missing" },
    });
    expect(
      screen.getByText("No leads match these filters"),
    ).toBeInTheDocument();
  });
  it("prepares a draft without starting a paid campaign", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<CampaignForm config={config} onClose={vi.fn()} onSave={save} />);
    fireEvent.change(screen.getByLabelText("Target businesses"), {
      target: { value: "Clinics" },
    });
    fireEvent.change(screen.getByLabelText("City"), {
      target: { value: "Austin" },
    });
    fireEvent.change(screen.getByLabelText("State / region"), {
      target: { value: "Texas" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save research plan" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0][0]).toMatchObject({
      source: "google_maps",
      niche: "Clinics",
      city: "Austin",
      max_leads: 10,
    });
    expect(api).not.toHaveBeenCalled();
  });
  it("persists business context", async () => {
    vi.mocked(api).mockResolvedValue({});
    render(
      <BusinessSettings
        profile={profile}
        refresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    fireEvent.change(screen.getByLabelText("What do you sell?"), {
      target: { value: "Local SEO for clinics" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/profile",
        "PUT",
        expect.objectContaining({ offer: "Local SEO for clinics" }),
      ),
    );
    expect(
      await screen.findByText(/Business profile saved/),
    ).toBeInTheDocument();
  });
  it("blocks qualification for an unverified contact and saves notes separately", async () => {
    vi.mocked(api).mockResolvedValue({});
    render(
      <LeadDetail
        lead={lead("b", "needs_review")}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.getByRole("option", { name: "Qualified" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Notes"), {
      target: { value: "Check service fit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/leads/b",
        "PATCH",
        expect.objectContaining({ notes: "Check service fit", stage: "new" }),
      ),
    );
    expect(
      screen.getByText(/does not have a NeverBounce-valid contact/),
    ).toBeInTheDocument();
  });
});
