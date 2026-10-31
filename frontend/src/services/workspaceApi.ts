import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export interface Profile {
  company_name: string;
  website: string;
  offer: string;
  ideal_customer: string;
  deal_size: string;
  geography: string;
  exclusions: string;
  buyer_roles: string;
}
export interface Source {
  id: string;
  name: string;
  provider: string;
  available: boolean;
  description: string;
  fields: string[];
  limits: string;
}
export interface Config {
  auth: { url: string; publishable_key: string; local_enabled: boolean };
  sources: Source[];
  integrations: { name: string; connected: boolean; purpose: string }[];
}
export type Stage =
  "new" | "qualified" | "contacted" | "meeting" | "won" | "lost" | "archived";
export type Category = "verified" | "needs_review" | "no_contact" | "excluded";
export interface CityInput {
  city: string;
  state: string;
  min_rank?: number | null;
  max_rank?: number | null;
}
export interface Plan {
  name: string;
  source: "google_maps" | "web_research" | "company_websites";
  niche: string;
  city: string;
  state: string;
  query: string;
  locations?: CityInput[];
  places_per_city?: number;
  websites: string[];
  max_leads: number;
  max_leads_per_company?: number | null;
  email_policy?: "accepted" | "valid_only";
  max_city_rounds?: number;
  rationale: string;
  qualification_criteria: string[];
  exclusions: string[];
  research_websites: boolean;
  min_google_maps_rank: number | null;
  max_google_maps_rank: number | null;
}
export interface Campaign {
  debug_log?: {
    id: number;
    at: string;
    event: string;
    level: "info" | "warning" | "error" | "success";
    message: string;
    domain?: string | null;
    details: Record<string, unknown>;
  }[];
  workflow?: string;
  id: string;
  plan: Plan;
  version: number;
  status: string;
  message: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  apify_run_id?: string;
  thread_id?: string;
  shortfall?: number;
  policy_version?: string;
  stop_reason?: string;
  diagnostics?: { version: number; counts: Record<string, number>; sequence?: number; reasons?: Record<string, Record<string, number>> };
  locations?: {
    city: string;
    state: string;
    status: string;
    discovered: number;
    processed: number;
    leads: number;
    round?: number;
    business_limit?: number;
  }[];
  recommendations?: {
    city: string;
    state: string;
    reason: string;
    evidence: Evidence[];
  }[];
  progress: {
    scraped?: number;
    duplicates?: number;
    checked?: number;
    cities_completed?: number;
    cities_total?: number;
    discovered: number;
    processed: number;
    verified: number;
    review: number;
    excluded: number;
    reused: number;
    target?: number;
    rejected?: number;
    no_contact?: number;
    verification_errors?: number;
  };
  events: { at: string; message: string }[];
  warnings: string[];
  usage: { requests: number; input_tokens: number; output_tokens: number };
}
export interface Evidence {
  title: string;
  url: string;
  observation: string;
}
export interface CRMLead {
  id: string;
  company: string;
  domain: string | null;
  industry: string;
  location: string;
  website: string | null;
  category: Category;
  stage: Stage;
  tags: string[];
  notes: string;
  next_action: string;
  follow_up: string;
  campaign_ids: string[];
  source: string;
  created_at: string;
  updated_at: string;
  activities: { at: string; message: string }[];
  assessment: {
    summary: string;
    fit: "strong" | "possible" | "poor" | "unknown";
    reasons: string[];
    unknowns: string[];
    evidence: Evidence[];
    excluded: boolean;
  };
  lead: {
    verified: boolean;
    enrichment_timestamp: string | null;
    failure_reason: string | null;
    contact_scope: string | null;
    contact_type: string | null;
    google_maps_rank: number | null;
    filter_reason: string | null;
    contact: {
      first_name: string | null;
      last_name: string | null;
      job_title: string | null;
      email: string;
      phone: string | null;
      linkedin: string | null;
      confidence: number | null;
    } | null;
    verification: {
      result: string;
      flags: string[];
      failure_reason?: string | null;
    } | null;
    business: { business_phone: string | null };
  };
}
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  at: string;
  campaign_ids?: string[];
  traces?: {
    id: string;
    tool: string;
    label: string;
    status: string;
    sources: { url?: string; title?: string }[];
  }[];
}
export interface Thread {
  id: string;
  title: string;
  messages: Message[];
  campaign_ids: string[];
  status: string;
  usage: { requests: number; input_tokens: number; output_tokens: number };
}
export interface Workspace {
  profile: Profile;
  campaigns: Campaign[];
  leads: CRMLead[];
  threads: { id: string; title: string; updated_at: string; status: string }[];
  account: { email: string | null; storage: "local" | "cloud" };
}

export let auth: SupabaseClient | null = null;
export function initializeAuth(config: Config) {
  if (config.auth.url && config.auth.publishable_key && !auth)
    auth = createClient(config.auth.url, config.auth.publishable_key);
  return auth;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const token = auth
    ? (await auth.auth.getSession()).data.session?.access_token
    : null;
  const response = await fetch("/api/workspace" + path, {
    method,
    credentials: "same-origin",
    signal,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: "Bearer " + token } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join(" ")
          : `Request failed (${response.status}). Please retry.`,
    );
  }
  return response.json();
}
export async function exportLeads(category = "verified", campaignId = "") {
  const token = auth
    ? (await auth.auth.getSession()).data.session?.access_token
    : null;
  const response = await fetch(
    "/api/workspace/leads/export?" +
      new URLSearchParams({ category, campaign_id: campaignId }),
    { headers: token ? { Authorization: "Bearer " + token } : {} },
  );
  if (!response.ok) throw new Error("Export failed. Please retry.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "genmantis_leads.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const active = (campaign: Campaign) =>
  [
    "queued",
    "discovering",
    "researching",
    "enriching",
    "recommending",
  ].includes(campaign.status);
export const stages: Stage[] = [
  "new",
  "qualified",
  "contacted",
  "meeting",
  "won",
  "lost",
  "archived",
];
export const stageName = (stage: string) =>
  ({
    new: "New lead",
    qualified: "Qualified",
    contacted: "Contacted",
    meeting: "Meeting booked",
    won: "Won",
    lost: "Lost",
    archived: "Archived",
  })[stage] || stage;
export const categoryName = (category: string) =>
  ({
    verified: "Verified",
    needs_review: "Needs review",
    no_contact: "No contact",
    excluded: "Excluded",
  })[category] || category;
export const sourceName = (source: string) =>
  ({
    google_maps: "Google Maps",
    web_research: "Web discovery",
    company_websites: "Company websites",
  })[source] || source;
export function safeLink(url: string | null | undefined) {
  if (!url) return undefined;
  try {
    const value = new URL(url.includes("://") ? url : "https://" + url);
    return ["https:", "http:"].includes(value.protocol)
      ? value.href
      : undefined;
  } catch {
    return undefined;
  }
}
export function dateLabel(date?: string | null) {
  return date
    ? new Date(date).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : "—";
}

export const verificationLabel = (result?: string | null) =>
  ({
    valid: "Valid",
    catchall: "Catch-all",
    unknown: "Unknown",
    invalid: "Invalid",
    disposable: "Disposable",
    verification_error: "Check failed",
  })[result || ""] || "Not checked";
