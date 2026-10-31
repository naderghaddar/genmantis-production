import { useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { api, type CRMLead } from "../../services/workspaceApi";
import { Modal } from "./Shared";

export default function DeleteLeadsDialog({ leads, onClose, onDeleted }: {
  leads: CRMLead[];
  onClose: () => void;
  onDeleted: (ids: string[]) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [removed, setRemoved] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const count = leads.length;
  async function remove() {
    if (inFlight.current || !count) return;
    inFlight.current = true;
    setBusy(true); setError("");
    let deleted = removed;
    try {
      const ids = leads.map((lead) => lead.id);
      if (!deleted) {
        if (count === 1) await api(`/leads/${encodeURIComponent(ids[0])}`, "DELETE");
        else await api("/leads/bulk", "DELETE", { ids });
        deleted = true;
        setRemoved(true);
      }
      await onDeleted(ids);
    } catch (err) {
      setError(deleted ? "Deletion succeeded, but the list could not refresh. Click Refresh list to try again." : (err as Error).message);
    } finally { setBusy(false); inFlight.current = false; }
  }
  return <Modal title={`Delete ${count === 1 ? "lead" : `${count} leads`}?`} onClose={() => { if (!busy) onClose(); }}>
    <div className="delete-leads-content">
      <p>Permanently remove {count === 1 ? "this lead" : `these ${count} leads`} and their notes from your database? This cannot be undone.</p>
      <ul className="delete-leads-list">{leads.map((lead) => <li key={lead.id}><strong>{lead.company}</strong><span>{lead.lead.contact?.email || lead.domain}</span></li>)}</ul>
      <p className="muted">Future searches may find these emails again. Search history is retained.</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <div className="modal-actions">
        <button type="button" className="btn-secondary" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="btn-danger" disabled={busy || !count} onClick={() => void remove()}><Trash2 size={15} />{busy ? "Please wait..." : removed ? "Refresh list" : `Delete ${count === 1 ? "lead" : `${count} leads`}`}</button>
      </div>
    </div>
  </Modal>;
}
