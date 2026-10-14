import { useEffect, useRef, useState, type FormEvent } from 'react';
import { confirmPlan, createConversation, editPlan, getConversation, sendAgentMessage, type Conversation } from '../services/agentApi';
import { downloadCsv, isActive } from '../services/api';
import SearchConfirmation from './SearchConfirmation';
import AgentRunProgress from './AgentRunProgress';

const STORAGE_KEY = 'genmantis_conversation';
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Unable to reach GenMantis. Please retry.';

export default function AgentChat() {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(true);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [pollPaused, setPollPaused] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const operation = useRef<AbortController | null>(null);
  const messageKey = useRef<{ message: string; id: string } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const focusAfterEdit = useRef(false);

  function accept(next: Conversation) {
    setConversation(next);
    localStorage.setItem(STORAGE_KEY, next.id);
  }

  useEffect(() => {
    const controller = new AbortController();
    const id = localStorage.getItem(STORAGE_KEY);
    const request = id ? getConversation(id, controller.signal) : createConversation(controller.signal);
    request.then(next => { if (!controller.signal.aborted) accept(next); })
      .catch(err => { if (!controller.signal.aborted) setError(errorText(err)); })
      .finally(() => { if (!controller.signal.aborted) setStarting(false); });
    return () => { controller.abort(); operation.current?.abort(); };
  }, []);

  useEffect(() => { end.current?.scrollIntoView?.({ block: 'nearest' }); }, [conversation?.messages.length, pending]);
  useEffect(() => {
    if (!busy && focusAfterEdit.current) { focusAfterEdit.current = false; input.current?.focus(); }
  }, [busy]);

  const run = conversation?.run ?? null;
  useEffect(() => {
    if (!conversation || !isActive(run) || pollPaused || busy) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getConversation(conversation!.id, controller.signal);
        if (controller.signal.aborted) return;
        accept(next);
        if (isActive(next.run)) timer = setTimeout(poll, 3000);
      } catch (err) {
        if (!controller.signal.aborted) { setError(errorText(err)); setPollPaused(true); }
      }
    }
    timer = setTimeout(poll, 1500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [conversation?.id, run?.run_id, run?.status, pollPaused, busy]);

  async function act(request: (signal: AbortSignal) => Promise<Conversation>) {
    if (operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError('');
    try {
      const next = await request(controller.signal);
      if (!controller.signal.aborted) accept(next);
      return true;
    } catch (err) { if (!controller.signal.aborted) setError(errorText(err)); return false; }
    finally { operation.current = null; if (!controller.signal.aborted) { setBusy(false); setPending(''); } }
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || !conversation || busy || operation.current) return;
    if (messageKey.current?.message !== message) messageKey.current = { message, id: crypto.randomUUID() };
    setPending(message);
    if (await act(signal => sendAgentMessage(conversation.id, message, messageKey.current!.id, signal))) {
      setText(''); messageKey.current = null;
    }
  }

  async function download(kind: 'verified' | 'all') {
    if (!run || operation.current || downloading) return;
    const controller = new AbortController();
    operation.current = controller;
    setDownloading(true); setError('');
    try { await downloadCsv(run.run_id, kind, controller.signal); }
    catch (err) { if (!controller.signal.aborted) setError(errorText(err)); }
    finally { operation.current = null; if (!controller.signal.aborted) setDownloading(false); }
  }

  return <section className="agent-chat">
    <div className="intro"><p className="eyebrow"><span /> YOUR NEXT BUSINESS CONNECTION</p>
      <h1>Start with a conversation.</h1><p className="description">Tell GenMantis who you'd like to reach. Review the plan, then find your leads.</p></div>
    <div className="chat-card">
      <div className="chat-toolbar"><strong>GenMantis assistant</strong><button className="text-button" disabled={busy || downloading || starting || isActive(run)} onClick={() => {
        localStorage.removeItem(STORAGE_KEY); setPollPaused(false); void act(createConversation);
      }}>New conversation</button></div>
      <div className="chat-messages" role="log" aria-label="Conversation">
        {starting && <p className="status">Opening your conversation...</p>}
        {conversation?.messages.map(message => <div className={`chat-message ${message.role}`} key={message.id}>
          <span className="message-author">{message.role === 'user' ? 'You' : 'GenMantis'}</span><p>{message.content}</p></div>)}
        {pending && <div className="chat-message user"><span className="message-author">You</span><p>{pending}</p></div>}
        {busy && <p className="status">{pending ? 'Thinking...' : 'Updating your search...'}</p>}
        <div ref={end} />
      </div>
      {conversation?.confirmation_required && <SearchConfirmation plan={conversation.plan} busy={busy || downloading} onConfirm={() => void act(signal => confirmPlan(conversation.plan, signal))} onEdit={async () => {
        focusAfterEdit.current = true; await act(signal => editPlan(conversation.plan, signal));
      }} />}
      {run && <AgentRunProgress run={run} downloading={downloading} onDownload={kind => void download(kind)} />}
      {error && <p className="error" role="alert">{error}</p>}
      {pollPaused && <button className="retry" onClick={() => { setError(''); setPollPaused(false); }}>Resume status check</button>}
      <form className="chat-composer" onSubmit={send}>
        <label htmlFor="agent-message" className="sr-only">Message GenMantis</label>
        <textarea id="agent-message" ref={input} maxLength={2000} rows={2} value={text} disabled={busy || downloading || starting || !conversation}
          placeholder="Find chiropractors in Austin, Texas outside the top 20 on Google Maps..."
          onChange={event => setText(event.target.value)} onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); }
          }} />
        <button className="primary" disabled={busy || downloading || starting || !conversation || !text.trim()} type="submit">Send</button>
      </form>
      <p className="chat-footnote">Every lead search requires your approval. Source searches collect up to 30 places.</p>
    </div>
  </section>;
}
