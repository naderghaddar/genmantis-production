import { useState } from "react";
import { ArrowRight, Columns3, GripVertical, Search } from "lucide-react";
import {
  api,
  type CRMLead,
  type Stage,
  type Workspace,
  stageName,
  dateLabel,
} from "../../services/workspaceApi";
import { Badge, Empty } from "./Shared";

const columns: Stage[] = ["new", "qualified", "contacted", "meeting", "won"];
export default function Pipeline({
  workspace,
  refresh,
  openLead,
  onResearch,
}: {
  workspace: Workspace;
  refresh: () => Promise<void>;
  openLead: (lead: CRMLead) => void;
  onResearch: () => void;
}) {
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState("");
  const leads = workspace.leads.filter(
    (l) =>
      !["excluded", "no_contact"].includes(l.category) &&
      !["lost", "archived"].includes(l.stage) &&
      [l.company, l.domain, l.industry]
        .join(" ")
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  async function move(id: string, stage: Stage) {
    setOver("");
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api("/leads/" + id, "PATCH", { stage });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-content pipeline-page">
      <div className="page-heading">
        <div>
          <p className="overline">TURN RESEARCH INTO RELATIONSHIPS</p>
          <h1>Your pipeline</h1>
          <p>
            Keep the next step clear. Drag leads between stages or open a card
            to update it.
          </p>
        </div>
        <div className="search-input">
          <Search size={16} />
          <input
            aria-label="Search pipeline"
            placeholder="Find a companyâ€¦"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {!workspace.leads.length ? (
        <Empty
          icon={<Columns3 size={28} />}
          title="Make room for your next opportunity"
          text="Your discovered contacts will appear here, ready to qualify and move through your sales process."
          action={
            <button className="btn-primary" onClick={onResearch}>
              Start researching
              <ArrowRight size={15} />
            </button>
          }
        />
      ) : (
        <div className="kanban">
          {columns.map((stage) => {
            const items = leads.filter((l) => l.stage === stage);
            return (
              <section
                key={stage}
                className={
                  "kanban-column " + (over === stage ? "drag-over" : "")
                }
                onDragOver={(e) => {
                  e.preventDefault();
                  setOver(stage);
                }}
                onDragLeave={() => setOver("")}
                onDrop={(e) => {
                  e.preventDefault();
                  const id = e.dataTransfer.getData("text/plain");
                  if (leads.some((l) => l.id === id)) void move(id, stage);
                }}
              >
                <div className="kanban-heading">
                  <i className={"stage-dot " + stage} />
                  <h3>{stageName(stage)}</h3>
                  <span>{items.length}</span>
                </div>
                <div className="kanban-cards">
                  {items.map((lead) => (
                    <article
                      className="kanban-card"
                      key={lead.id}
                      draggable={!busy}
                      onDragStart={(e) =>
                        e.dataTransfer.setData("text/plain", lead.id)
                      }
                    >
                      <div className="kanban-card-top">
                        <span className="company-avatar">
                          {lead.company.slice(0, 2).toUpperCase()}
                        </span>
                        <GripVertical size={15} />
                      </div>
                      <button
                        className="card-title"
                        onClick={() => openLead(lead)}
                      >
                        {lead.company}
                      </button>
                      <p>{lead.industry}</p>
                      <Badge value={lead.category} />
                      {lead.next_action && (
                        <div className="next-action">{lead.next_action}</div>
                      )}
                      <footer>
                        <span>
                          {lead.lead.contact?.first_name || "Company contact"}
                        </span>
                        <span>
                          {lead.follow_up
                            ? "Follow up " + dateLabel(lead.follow_up)
                            : dateLabel(lead.created_at)}
                        </span>
                      </footer>
                      <select
                        aria-label={"Move " + lead.company + " to stage"}
                        disabled={busy}
                        value={lead.stage}
                        onChange={(e) =>
                          void move(lead.id, e.target.value as Stage)
                        }
                      >
                        {[...columns, "lost", "archived"].map((s) => (
                          <option
                            value={s}
                            key={s}
                            disabled={
                              s === "qualified" && lead.category !== "verified"
                            }
                          >
                            {stageName(s)}
                          </option>
                        ))}
                      </select>
                    </article>
                  ))}
                  {!items.length && (
                    <div className="kanban-placeholder">
                      No leads in this stage
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
