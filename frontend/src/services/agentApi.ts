import { checkResponse, type RunStatus } from './api';

export interface SearchPlan {
  id: string;
  version: number;
  niche: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  business_size_preference: string | null;
  min_google_maps_rank: number | null;
  max_google_maps_rank: number | null;
  max_leads: number;
  additional_preferences: string[];
  unsupported_preferences: string[];
  limitations: string[];
  status: 'collecting_requirements' | 'ready_for_confirmation' | 'confirmed' | 'running' | 'completed' | 'failed';
}
export interface Conversation {
  id: string;
  messages: { id: string; role: 'user' | 'assistant'; content: string }[];
  plan: SearchPlan;
  confirmation_required: boolean;
  run: RunStatus | null;
  usage: { input_tokens: number; output_tokens: number; requests: number };
}

async function request(path: string, signal: AbortSignal, body?: unknown): Promise<Conversation> {
  const response = await fetch('/api/agent' + path, { signal, credentials: 'same-origin',
    ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  return (await checkResponse(response)).json();
}
export const createConversation = (signal: AbortSignal) => request('/conversations', signal, {});
export const getConversation = (id: string, signal: AbortSignal) => request(`/conversations/${encodeURIComponent(id)}`, signal);
export const sendAgentMessage = (id: string, message: string, messageId: string, signal: AbortSignal) =>
  request(`/conversations/${encodeURIComponent(id)}/messages`, signal, { message, message_id: messageId });
export const confirmPlan = (plan: SearchPlan, signal: AbortSignal) => request(`/search-plans/${encodeURIComponent(plan.id)}/confirm`, signal, { version: plan.version });
export const editPlan = (plan: SearchPlan, signal: AbortSignal) => request(`/search-plans/${encodeURIComponent(plan.id)}/edit`, signal, { version: plan.version });
