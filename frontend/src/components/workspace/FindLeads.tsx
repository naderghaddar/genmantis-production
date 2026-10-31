import { useRef, useState, type FormEvent } from "react";
import { Download, Plus, Search, Trash2, Upload } from "lucide-react";
import { active, api, type Campaign, type Workspace, type CityInput } from "../../services/workspaceApi";
import SearchRun from "./SearchRun";

type CityRow = { id: number; city: string; state: string; min: string; max: string };

export default function FindLeads({ workspace, refresh, review }: {
  workspace: Workspace;
  refresh: () => Promise<void>;
  review: (campaign: Campaign) => void;
}) {
  const nextId = useRef(1);
  const inFlight = useRef(false);
  const [niche, setNiche] = useState("");
  const [places, setPlaces] = useState(100);
  const [rows, setRows] = useState<CityRow[]>([{ id: 0, city: "", state: "", min: "", max: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const running = workspace.campaigns.some(active);

  function update(id: number, field: keyof Omit<CityRow, "id">, value: string) {
    setRows((current) => current.map((row) => row.id === id ? { ...row, [field]: value } : row));
  }

  async function importCsv(file?: File) {
    if (!file || inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(""); setNotice("");
    try {
      if (file.size > 500000) throw new Error("Choose a CSV smaller than 500 KB (up to 500 cities).");
      const result = await api<{ locations: CityInput[] }>("/cities/import", "POST", { csv: await file.text() });
      setRows(result.locations.map((city) => ({ id: nextId.current++, city: city.city, state: city.state,
        min: city.min_rank?.toString() || "", max: city.max_rank?.toString() || "" })));
      setNotice(`Imported ${result.locations.length} cities. Review the rows before starting.`);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); inFlight.current = false; }
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || running) return;
    inFlight.current = true;
    setBusy(true); setError(""); setNotice("");
    try {
      const locations = rows.map((row) => ({ city: row.city.trim(), state: row.state.trim(),
        min_rank: row.min ? Number(row.min) : null, max_rank: row.max ? Number(row.max) : null }));
      if (locations.some((city) => city.min_rank && city.max_rank && city.min_rank > city.max_rank))
        throw new Error("Minimum rank must not exceed maximum rank.");
      const campaign = await api<Campaign>("/campaigns", "POST", { niche: niche.trim(), locations, places_per_city: places });
      await api(`/campaigns/${campaign.id}/start`, "POST", { version: campaign.version });
      setNotice("Search started. You can follow progress below or open the lead database.");
    } catch (err) { setError((err as Error).message); }
    finally {
      try { await refresh(); } catch (err) { setError((previous) => previous || (err as Error).message); }
      setBusy(false); inFlight.current = false;
    }
  }

  return <div className="page-content simple-search">
    <div className="page-heading"><div>
      <p className="overline">GOOGLE MAPS → HUNTER → NEVERBOUNCE</p>
      <h1>Find leads</h1>
      <p>Enter a niche and cities. Scrape each city, remove duplicate domains, then check up to two people per company.</p>
    </div></div>
    <form className="data-card search-form" onSubmit={(event) => void start(event)}>
      <fieldset disabled={busy}>
        <div className="search-options">
          <label>Niche / keyword<input required maxLength={200} value={niche} onChange={(event) => setNiche(event.target.value)} placeholder="e.g. chiropractor" /></label>
          <label>Businesses per city<select value={places} onChange={(event) => setPlaces(Number(event.target.value))}>
            {[100, 200, 300, 400, 500].map((count) => <option key={count} value={count}>Up to {count}</option>)}
          </select></label>
        </div>
        <div className="city-heading"><div><h2>Cities</h2><p>Searches run in the order below. Importing a CSV replaces these rows.</p></div>
          <div className="search-buttons">
            <a className="btn-secondary small" href={"data:text/csv;charset=utf-8," + encodeURIComponent("city,state,rank\nSpokane,Washington,100\nBoise,Idaho,100\n")} download="cities-template.csv"><Download size={15} /> CSV template</a>
            <label className="btn-secondary small csv-upload"><Upload size={15} /> Import CSV
              <input type="file" accept=".csv,text/csv" aria-label="Import cities CSV" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; void importCsv(file); }} />
            </label>
          </div>
        </div>
        <p className="rank-help">Optional rank filters are inclusive. CSV columns: <code>city,state,rank</code> (rank = maximum), or <code>city,state,min_rank,max_rank</code>. Leave ranks blank for all results. Results without an established organic rank are skipped when a filter is set.</p>
        <div className="city-rows">
          {rows.map((row, position) => <div className="city-row" key={row.id}>
            <span className="city-number">{position + 1}</span>
            <label>City<input required maxLength={200} aria-label={`City ${position + 1}`} placeholder="Spokane" value={row.city} onChange={(event) => update(row.id, "city", event.target.value)} /></label>
            <label>State / region<input required maxLength={200} aria-label={`State ${position + 1}`} placeholder="Washington" value={row.state} onChange={(event) => update(row.id, "state", event.target.value)} /></label>
            <label>Min rank<input type="number" min={1} max={10000} step={1} aria-label={`Minimum rank ${position + 1}`} placeholder="Any" value={row.min} onChange={(event) => update(row.id, "min", event.target.value)} /></label>
            <label>Max rank<input type="number" min={1} max={10000} step={1} aria-label={`Maximum rank ${position + 1}`} placeholder="Any" value={row.max} onChange={(event) => update(row.id, "max", event.target.value)} /></label>
            <button className="icon-button" type="button" aria-label={`Remove city ${position + 1}`} disabled={rows.length === 1} onClick={() => setRows((current) => current.filter((city) => city.id !== row.id))}><Trash2 size={16} /></button>
          </div>)}
        </div>
        <button className="btn-secondary small" type="button" disabled={rows.length >= 500} onClick={() => setRows((current) => [...current, { id: nextId.current++, city: "", state: "", min: "", max: "" }])}><Plus size={15} /> Add city</button>
        <div className="search-submit"><p>Decision-makers first, then other personal emails. Names are optional. Save valid, catch-all and unknown emails. Existing emails are skipped.</p>
          <button className="btn-primary" type="submit" disabled={running || busy}><Search size={16} />{busy ? "Please wait…" : running ? "Search in progress" : "Start search"}</button>
        </div>
      </fieldset>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {notice && <p className="search-notice" role="status">{notice}</p>}
    </form>
    <div className="search-history"><h2>Search history</h2>
      {!workspace.campaigns.length && <p className="muted">Your searches and saved-lead counts will appear here.</p>}
      {workspace.campaigns.map((campaign) => <SearchRun key={campaign.id} campaign={campaign} refresh={refresh} viewLeads={() => review(campaign)} />)}
    </div>
  </div>;
}
