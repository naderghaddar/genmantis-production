import { useMemo, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Search,
  SlidersHorizontal,
  Trash2,
  Users,
  X,
} from "lucide-react";
import {
  api,
  type CRMLead,
  type Workspace,
  verificationLabel,
  dateLabel,
  exportLeads,
  sourceName,
  stageName,
  stages,
  type Stage,
} from "../../services/workspaceApi";
import { Badge, Empty } from "./Shared";
import DeleteLeadsDialog from "./DeleteLeadsDialog";

export default function Leads({
  workspace,
  refresh,
  openLead,
  onResearch,
  initialCategory = "all",
  initialCampaign = "",
}: {
  workspace: Workspace;
  refresh: () => Promise<void>;
  openLead: (lead: CRMLead) => void;
  onResearch: () => void;
  initialCategory?: string;
  initialCampaign?: string;
}) {
  const [category, setCategory] = useState(initialCategory);
  const [query, setQuery] = useState("");
  const [industry, setIndustry] = useState("");
  const [stage, setStage] = useState("");
  const [campaign, setCampaign] = useState(initialCampaign);
  const [sort, setSort] = useState("recent");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkStage, setBulkStage] = useState<Stage>("qualified");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState(!!initialCampaign);
  const [deleting, setDeleting] = useState<CRMLead[] | null>(null);
  const industries = [
    ...new Set(workspace.leads.map((lead) => lead.industry)),
  ].sort();
  const filtered = useMemo(
    () =>
      workspace.leads
        .filter(
          (lead) =>
            (category === "all" ||
              lead.lead.verification?.result === category) &&
            (!industry || lead.industry === industry) &&
            (!stage || lead.stage === stage) &&
            (!campaign || lead.campaign_ids.includes(campaign)) &&
            [
              lead.company,
              lead.domain,
              lead.location,
              lead.industry,
              lead.lead.contact?.email,
              lead.lead.contact?.first_name,
              lead.lead.contact?.last_name,
              ...lead.tags,
            ]
              .join(" ")
              .toLowerCase()
              .includes(query.toLowerCase()),
        )
        .sort((a, b) =>
          sort === "name"
            ? a.company.localeCompare(b.company)
            : b.created_at.localeCompare(a.created_at),
        ),
    [workspace.leads, category, query, industry, stage, campaign, sort],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 20));
  const currentPage = Math.min(page, pages - 1);
  const rows = filtered.slice(currentPage * 20, currentPage * 20 + 20);
  function chooseCategory(value: string) {
    setCategory(value);
    setPage(0);
    setSelected([]);
  }
  async function bulk() {
    setBusy(true);
    setError("");
    try {
      await api("/leads/bulk", "PATCH", {
        ids: selected,
        changes: { stage: bulkStage },
      });
      setSelected([]);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    setBusy(true);
    setError("");
    try {
      await exportLeads(category === "all" ? "verified" : category, campaign);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <p className="overline">YOUR RELATIONSHIP WORKSPACE</p>
          <h1>
            Lead database{" "}
            <span className="count-tag">{workspace.leads.length}</span>
          </h1>
          <p>
            People for your SEO outreach. Verified includes valid, catch-all and
            unknown email results.
          </p>
        </div>
        <button
          className="btn-secondary"
          disabled={busy || !workspace.leads.length}
          onClick={() => void download()}
        >
          <ArrowDownToLine size={16} />
          {category === "all" || category === "verified"
            ? "Export verified"
            : "Export category"}
        </button>
      </div>
      <div className="lead-tabs">
        {["all", "valid", "catchall", "unknown"].map((value) => (
          <button
            className={category === value ? "active" : ""}
            key={value}
            onClick={() => chooseCategory(value)}
          >
            {value === "all" ? "All leads" : verificationLabel(value)}
            <span>
              {value === "all"
                ? workspace.leads.length
                : workspace.leads.filter(
                    (l) => l.lead.verification?.result === value,
                  ).length}
            </span>
          </button>
        ))}
      </div>
      <div className="data-card">
        <div className="table-toolbar">
          <div className="search-input">
            <Search size={16} />
            <input
              aria-label="Search leads"
              placeholder="Search companies, contacts, tags…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
            />
            {query && (
              <button
                className="icon-button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <button
            className={"btn-secondary small " + (filters ? "selected" : "")}
            onClick={() => setFilters(!filters)}
          >
            <SlidersHorizontal size={14} /> Filters{" "}
            {(industry || stage || campaign) && <i className="filter-dot" />}
          </button>
          <select
            aria-label="Sort leads"
            className="sort-select"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="recent">Recently added</option>
            <option value="name">Company A–Z</option>
          </select>
        </div>
        {filters && (
          <div className="filter-row">
            <select
              aria-label="Industry filter"
              value={industry}
              onChange={(e) => {
                setIndustry(e.target.value);
                setPage(0);
              }}
            >
              <option value="">All industries</option>
              {industries.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
            <select
              aria-label="Stage filter"
              value={stage}
              onChange={(e) => {
                setStage(e.target.value);
                setPage(0);
              }}
            >
              <option value="">All stages</option>
              {stages.map((value) => (
                <option key={value} value={value}>
                  {stageName(value)}
                </option>
              ))}
            </select>
            <select
              aria-label="Search filter"
              value={campaign}
              onChange={(e) => {
                setCampaign(e.target.value);
                setPage(0);
              }}
            >
              <option value="">All searches</option>
              {workspace.campaigns.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.plan.name}
                </option>
              ))}
            </select>
            <button
              className="text-link"
              onClick={() => {
                setIndustry("");
                setStage("");
                setCampaign("");
              }}
            >
              Reset
            </button>
          </div>
        )}
        {!!selected.length && (
          <div className="bulk-bar">
            <strong>{selected.length} selected</strong>
            <select
              aria-label="Bulk lead stage"
              value={bulkStage}
              onChange={(e) => setBulkStage(e.target.value as Stage)}
            >
              {stages.map((value) => (
                <option value={value} key={value}>
                  {stageName(value)}
                </option>
              ))}
            </select>
            <button
              className="btn-primary small"
              disabled={busy}
              onClick={() => void bulk()}
            >
              Move leads
            </button>
            <button className="text-link" onClick={() => setSelected([])}>
              Clear
            </button>
            <button className="btn-danger small" disabled={busy || !workspace.leads.some((lead) => selected.includes(lead.id))}
              onClick={() => setDeleting(workspace.leads.filter((lead) => selected.includes(lead.id)))}>
              <Trash2 size={15} /> Delete selected
            </button>
          </div>
        )}
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {filtered.length ? (
          <>
            <div className="table-overflow">
              <table className="leads-table">
                <thead>
                  <tr>
                    <th className="check-cell">
                      <input
                        type="checkbox"
                        aria-label="Select visible leads"
                        checked={
                          rows.length > 0 &&
                          rows.every((l) => selected.includes(l.id))
                        }
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [
                                  ...new Set([
                                    ...selected,
                                    ...rows.map((l) => l.id),
                                  ]),
                                ].slice(0, 100)
                              : selected.filter(
                                  (id) => !rows.some((l) => l.id === id),
                                ),
                          )
                        }
                      />
                    </th>
                    <th>Company</th>
                    <th>Person</th>
                    <th>Email</th>
                    <th>Verification</th>
                    <th>Maps rank</th>
                    <th>Stage</th>
                    <th>Added</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((lead) => (
                    <tr key={lead.id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={"Select " + lead.company}
                          checked={selected.includes(lead.id)}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...selected, lead.id].slice(0, 100)
                                : selected.filter((id) => id !== lead.id),
                            )
                          }
                        />
                      </td>
                      <td>
                        <button
                          className="company-cell"
                          onClick={() => openLead(lead)}
                        >
                          <span className="company-avatar">
                            {lead.company.slice(0, 2).toUpperCase()}
                          </span>
                          <span>
                            <strong>{lead.company}</strong>
                            <small>{lead.domain || lead.industry}</small>
                          </span>
                        </button>
                      </td>
                      <td>
                        <div className="contact-cell">
                          <span>
                            {lead.lead.contact
                              ? [
                                  lead.lead.contact.first_name,
                                  lead.lead.contact.last_name,
                                ]
                                  .filter(Boolean)
                                  .join(" ") || "Name unavailable"
                              : "No contact found"}
                          </span>
                          <small>
                            {lead.lead.contact?.job_title ||
                              lead.location ||
                              sourceName(lead.source)}
                          </small>
                        </div>
                      </td>
                      <td className="lead-email">{lead.lead.contact?.email}</td>
                      <td>
                        <Badge
                          value={
                            lead.lead.verification?.result === "valid"
                              ? "verified"
                              : "needs_review"
                          }
                        >
                          {verificationLabel(lead.lead.verification?.result)}
                        </Badge>
                      </td>
                      <td>
{lead.lead.google_maps_rank ?? "Unavailable"}
                      </td>
                      <td>
                        <span className={"stage-label stage-" + lead.stage}>
                          {stageName(lead.stage)}
                        </span>
                      </td>
                      <td className="muted nowrap">
                        {dateLabel(lead.created_at)}
                      </td>
                      <td>
                        <div className="lead-row-actions">
                        <button
                          aria-label={"Open " + lead.company}
                          className="icon-button"
                          onClick={() => openLead(lead)}
                        >
                          <ArrowUpRight size={16} />
                        </button>
                        <button className="icon-button delete-lead-button" aria-label={`Delete ${lead.lead.contact?.email || lead.company}`}
                          title="Delete lead" disabled={busy} onClick={() => setDeleting([lead])}>
                          <Trash2 size={15} />
                        </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <span>
                {currentPage * 20 + 1}–
                {Math.min((currentPage + 1) * 20, filtered.length)} of{" "}
                {filtered.length} leads
              </span>
              <div>
                <button
                  className="icon-button"
                  aria-label="Previous page"
                  disabled={!currentPage}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ChevronLeft size={17} />
                </button>
                <span>
                  Page {currentPage + 1} of {pages}
                </span>
                <button
                  className="icon-button"
                  aria-label="Next page"
                  disabled={currentPage + 1 >= pages}
                  onClick={() => setPage(currentPage + 1)}
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </div>
          </>
        ) : (
          <Empty
            icon={<Users size={28} />}
            title={
              workspace.leads.length
                ? "No leads match these filters"
                : "Your next customers belong here"
            }
            text={
              workspace.leads.length
                ? "Try another search or clear your filters."
                : "Enter a niche and cities, or import a city CSV. People with accepted email checks appear here automatically."
            }
            action={
              <button
                className="btn-primary"
                onClick={
                  workspace.leads.length
                    ? () => {
                        setQuery("");
                        setIndustry("");
                        setStage("");
                        setCampaign("");
                        setCategory("all");
                      }
                    : onResearch
                }
              >
                {workspace.leads.length
                  ? "Clear filters"
                  : "Find your first leads"}
                <ArrowUpRight size={15} />
              </button>
            }
          />
        )}
      </div>
      {deleting && <DeleteLeadsDialog leads={deleting} onClose={() => setDeleting(null)} onDeleted={async (ids) => {
        await refresh();
        setSelected((current) => current.filter((id) => !ids.includes(id)));
        setDeleting(null);
      }} />}
    </div>
  );
}
