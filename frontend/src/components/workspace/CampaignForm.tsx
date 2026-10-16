import { useState, type FormEvent } from "react";
import { ArrowRight, Globe2, MapPin, ShieldCheck } from "lucide-react";
import {
  type Campaign,
  type Config,
  type Plan,
  sourceName,
} from "../../services/workspaceApi";
import { Modal } from "./Shared";

export const initialPlan: Plan = {
  name: "",
  source: "google_maps",
  niche: "",
  city: "",
  state: "",
  query: "",
  websites: [],
  max_leads: 10,
  rationale: "",
  qualification_criteria: [],
  exclusions: [],
  research_websites: true,
  min_google_maps_rank: null,
  max_google_maps_rank: null,
};
export default function CampaignForm({
  campaign,
  config,
  onClose,
  onSave,
}: {
  campaign?: Campaign | null;
  config: Config;
  onClose: () => void;
  onSave: (plan: Plan, campaign?: Campaign | null) => Promise<void>;
}) {
  const [plan, setPlan] = useState<Plan>(campaign?.plan || initialPlan);
  const [websites, setWebsites] = useState(plan.websites.join("\n"));
  const [criteria, setCriteria] = useState(
    plan.qualification_criteria.join("\n"),
  );
  const [exclusions, setExclusions] = useState(plan.exclusions.join("\n"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = <K extends keyof Plan>(key: K, value: Plan[K]) =>
    setPlan((old) => ({ ...old, [key]: value }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSave(
        {
          ...plan,
          name:
            plan.name ||
            `${plan.niche} · ${plan.city || sourceName(plan.source)}`,
          websites: websites
            .split(/[\n,]+/)
            .map((v) => v.trim())
            .filter(Boolean),
          qualification_criteria: criteria
            .split("\n")
            .map((v) => v.trim())
            .filter(Boolean),
          exclusions: exclusions
            .split("\n")
            .map((v) => v.trim())
            .filter(Boolean),
        },
        campaign,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save campaign.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={campaign ? "Edit research plan" : "Create a campaign"}
      onClose={onClose}
      wide
    >
      <form onSubmit={submit} className="campaign-form">
        <p className="muted">
          Define who you want to find. You’ll review the plan before any
          discovery or enrichment starts.
        </p>
        <div className="source-options">
          {config.sources.map((source) => (
            <button
              key={source.id}
              type="button"
              className={
                "source-option " + (plan.source === source.id ? "selected" : "")
              }
              onClick={() =>
                setPlan((old) => ({
                  ...old,
                  source: source.id as Plan["source"],
                  min_google_maps_rank: null,
                  max_google_maps_rank: null,
                }))
              }
            >
              {source.id === "google_maps" ? (
                <MapPin size={19} />
              ) : (
                <Globe2 size={19} />
              )}
              <strong>{source.name}</strong>
              <span>{source.provider}</span>
            </button>
          ))}
        </div>
        <label>
          Campaign name{" "}
          <input
            value={plan.name}
            maxLength={120}
            placeholder="e.g. Independent clinics · Austin"
            onChange={(e) => update("name", e.target.value)}
          />
        </label>
        <label>
          Target businesses{" "}
          <input
            required
            value={plan.niche}
            maxLength={200}
            placeholder="e.g. Independent dental practices"
            onChange={(e) => update("niche", e.target.value)}
          />
        </label>
        {plan.source !== "company_websites" && (
          <div className="form-grid">
            <label>
              City{" "}
              <input
                required={plan.source === "google_maps"}
                value={plan.city}
                maxLength={200}
                placeholder="Austin"
                onChange={(e) => update("city", e.target.value)}
              />
            </label>
            <label>
              State / region{" "}
              <input
                required={plan.source === "google_maps"}
                value={plan.state}
                maxLength={200}
                placeholder="Texas"
                onChange={(e) => update("state", e.target.value)}
              />
            </label>
          </div>
        )}
        {plan.source === "web_research" && (
          <label>
            Discovery query{" "}
            <textarea
              required
              value={plan.query}
              maxLength={1000}
              placeholder="B2B logistics software companies in Canada with a public product website"
              onChange={(e) => update("query", e.target.value)}
            />
          </label>
        )}
        {plan.source === "company_websites" && (
          <label>
            Company websites{" "}
            <textarea
              required
              rows={4}
              value={websites}
              placeholder={"https://company.com\nhttps://another-company.com"}
              onChange={(e) => setWebsites(e.target.value)}
            />
            <small>
              One website per line, up to 30. Contacts will be found through
              Hunter.
            </small>
          </label>
        )}
        <div className="form-grid">
          <label>
            Maximum businesses to enrich{" "}
            <input
              type="number"
              min={1}
              max={30}
              value={plan.max_leads}
              onChange={(e) => update("max_leads", Number(e.target.value))}
            />
          </label>
          {plan.source === "google_maps" && (
            <label>
              Minimum Maps position{" "}
              <input
                type="number"
                min={1}
                max={10000}
                value={plan.min_google_maps_rank ?? ""}
                placeholder="Optional · e.g. 21"
                onChange={(e) =>
                  update(
                    "min_google_maps_rank",
                    e.target.value ? Number(e.target.value) : null,
                  )
                }
              />
            </label>
          )}
        </div>
        {plan.source === "google_maps" && (
          <label>
            Maximum Maps position{" "}
            <input
              type="number"
              min={1}
              max={10000}
              value={plan.max_google_maps_rank ?? ""}
              placeholder="Optional"
              onChange={(e) =>
                update(
                  "max_google_maps_rank",
                  e.target.value ? Number(e.target.value) : null,
                )
              }
            />
            <small>
              Maps discovery examines up to 30 source places; filters can return
              fewer matches.
            </small>
          </label>
        )}
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={plan.research_websites}
            onChange={(e) => update("research_websites", e.target.checked)}
          />
          <span>
            <strong>Research company websites</strong>
            <small>
              Collect evidence and assess fit before finding contacts. Uses
              additional model and web-search calls.
            </small>
          </span>
        </label>
        {plan.research_websites && (
          <div className="form-grid">
            <label>
              Qualification criteria{" "}
              <textarea
                rows={3}
                value={criteria}
                placeholder={
                  "Offers commercial services\nServes small businesses"
                }
                onChange={(e) => setCriteria(e.target.value)}
              />
              <small>
                One per line, up to 6. Missing evidence stays unknown.
              </small>
            </label>
            <label>
              Exclude businesses that…{" "}
              <textarea
                rows={3}
                value={exclusions}
                placeholder={"Are national franchises\nOnly serve consumers"}
                onChange={(e) => setExclusions(e.target.value)}
              />
            </label>
          </div>
        )}
        <label>
          Why this campaign fits{" "}
          <textarea
            value={plan.rationale}
            maxLength={3000}
            placeholder="The customer problem or opportunity you want to explore"
            onChange={(e) => update("rationale", e.target.value)}
          />
        </label>
        <div className="verification-note">
          <ShieldCheck size={19} />
          <span>
            Hunter finds contacts. NeverBounce checks every selected email. Only
            valid results receive a Verified badge.
          </span>
        </div>
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save research plan"}
            <ArrowRight size={15} />
          </button>
        </div>
      </form>
    </Modal>
  );
}
