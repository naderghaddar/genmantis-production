import { useState } from "react";
import {
  Building2,
  Check,
  Clock3,
  FileText,
  Mail,
  ShieldCheck,
} from "lucide-react";
import {
  type CRMLead,
  type Stage,
  api,
  categoryName,
  dateLabel,
  sourceName,
  stages,
  stageName,
} from "../../services/workspaceApi";
import { Badge, ExternalLink, Modal } from "./Shared";

export default function LeadDetail({
  lead,
  onClose,
  onSaved,
}: {
  lead: CRMLead;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [stage, setStage] = useState(lead.stage);
  const [notes, setNotes] = useState(lead.notes);
  const [tags, setTags] = useState(lead.tags.join(", "));
  const [nextAction, setNextAction] = useState(lead.next_action);
  const [followUp, setFollowUp] = useState(lead.follow_up?.slice(0, 10) || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const contact = lead.lead.contact;
  async function save() {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await api("/leads/" + lead.id, "PATCH", {
        stage,
        notes,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        next_action: nextAction,
        follow_up: followUp,
      });
      await onSaved();
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Lead details" onClose={onClose} wide>
      <div className="lead-detail">
        <div className="lead-identity">
          <div className="company-avatar large">
            {lead.company.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <h2>{lead.company}</h2>
            <ExternalLink url={lead.website}>
              {lead.domain || "Website unavailable"}
            </ExternalLink>
            <p>
              {lead.industry} <span>·</span>{" "}
              {lead.location || "Location unknown"}
            </p>
          </div>
          <Badge value={lead.category} />
        </div>
        <div className="detail-columns">
          <div>
            <section className="detail-section">
              <h3>
                <Mail size={16} /> Contact
              </h3>
              {contact ? (
                <>
                  <h4>
                    {[contact.first_name, contact.last_name]
                      .filter(Boolean)
                      .join(" ") || "Company contact"}
                  </h4>
                  <p className="muted">
                    {contact.job_title ||
                      (lead.lead.contact_type === "generic"
                        ? "Company inbox"
                        : "Role unavailable")}
                  </p>
                  <div className="contact-email">{contact.email}</div>
                  {contact.phone && <p>{contact.phone}</p>}
                  {contact.linkedin && (
                    <ExternalLink url={contact.linkedin}>
                      LinkedIn profile
                    </ExternalLink>
                  )}
                  <small>
                    Contact sourced from Hunter. Company-level affiliation;
                    local branch affiliation may be unknown.
                  </small>
                </>
              ) : (
                <p className="muted">
                  No suitable Hunter contact was found. This business remains
                  available for review.
                </p>
              )}
            </section>
            <section className="detail-section">
              <h3>
                <ShieldCheck size={16} /> Verification
              </h3>
              <div className="verification-result">
                <Badge value={lead.category}>
                  {categoryName(lead.category)}
                </Badge>
                <span>{lead.lead.verification?.result || "Not checked"}</span>
              </div>
              <p className="muted">
                {lead.lead.verified
                  ? "NeverBounce returned valid for this selected email."
                  : "This record does not have a NeverBounce-valid contact. It is excluded from verified-only exports."}
              </p>
              <small>
                Last processed {dateLabel(lead.lead.enrichment_timestamp)}
              </small>
              {lead.lead.failure_reason && (
                <p className="detail-warning">{lead.lead.failure_reason}</p>
              )}
            </section>
            <section className="detail-section">
              <h3>
                <Building2 size={16} /> Discovery
              </h3>
              <dl className="detail-list">
                <dt>Source</dt>
                <dd>{sourceName(lead.source)}</dd>
                <dt>Added</dt>
                <dd>{dateLabel(lead.created_at)}</dd>
                <dt>Maps position</dt>
                <dd>{lead.lead.google_maps_rank || "Not established"}</dd>
                <dt>Business phone</dt>
                <dd>{lead.lead.business?.business_phone || "Unavailable"}</dd>
              </dl>
              {lead.lead.filter_reason && (
                <small>{lead.lead.filter_reason.replaceAll("_", " ")}</small>
              )}
            </section>
          </div>
          <div>
            <section className="detail-section">
              <h3>
                <FileText size={16} /> Research & fit{" "}
                <Badge value={lead.assessment.fit}>
                  {lead.assessment.fit === "unknown"
                    ? "Needs assessment"
                    : lead.assessment.fit + " fit"}
                </Badge>
              </h3>
              <p>{lead.assessment.summary}</p>
              {lead.assessment.reasons.map((reason, i) => (
                <p className="research-reason" key={i}>
                  <Check size={13} />
                  {reason}
                </p>
              ))}
              {!!lead.assessment.unknowns.length && (
                <div className="unknowns">
                  <strong>Still unknown</strong>
                  {lead.assessment.unknowns.map((value, i) => (
                    <p key={i}>{value}</p>
                  ))}
                </div>
              )}
              {lead.assessment.evidence.map((item, i) => (
                <div className="evidence-card" key={i}>
                  <ExternalLink url={item.url}>{item.title}</ExternalLink>
                  <p>{item.observation}</p>
                </div>
              ))}
            </section>
            <section className="detail-section">
              <h3>Relationship</h3>
              <label>
                Pipeline stage
                <select
                  value={stage}
                  onChange={(e) => {
                    setStage(e.target.value as Stage);
                    setSaved(false);
                  }}
                >
                  {stages.map((s) => (
                    <option
                      key={s}
                      value={s}
                      disabled={
                        s === "qualified" && lead.category !== "verified"
                      }
                    >
                      {stageName(s)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Tags
                <input
                  value={tags}
                  maxLength={500}
                  placeholder="Priority, local, Q4"
                  onChange={(e) => {
                    setTags(e.target.value);
                    setSaved(false);
                  }}
                />
              </label>
              <label>
                Next action
                <input
                  value={nextAction}
                  maxLength={500}
                  placeholder="e.g. Review their service page"
                  onChange={(e) => {
                    setNextAction(e.target.value);
                    setSaved(false);
                  }}
                />
              </label>
              <label>
                Follow-up date
                <input
                  type="date"
                  value={followUp}
                  onChange={(e) => {
                    setFollowUp(e.target.value);
                    setSaved(false);
                  }}
                />
              </label>
              <label>
                Notes
                <textarea
                  rows={4}
                  value={notes}
                  maxLength={10000}
                  placeholder="What makes this prospect a good fit?"
                  onChange={(e) => {
                    setNotes(e.target.value);
                    setSaved(false);
                  }}
                />
              </label>
            </section>
          </div>
        </div>
        <section className="detail-section">
          <h3>
            <Clock3 size={16} /> Activity
          </h3>
          <div className="activity-list">
            {lead.activities
              .slice(-8)
              .reverse()
              .map((item, i) => (
                <div key={i}>
                  <i />
                  <p>{item.message}</p>
                  <time>{dateLabel(item.at)}</time>
                </div>
              ))}
          </div>
        </section>
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <span className="save-status">
            {saved && (
              <>
                <Check size={14} /> Changes saved
              </>
            )}
          </span>
          <button className="btn-secondary" onClick={onClose}>
            Close
          </button>
          <button
            className="btn-primary"
            onClick={() => void save()}
            disabled={busy}
          >
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
