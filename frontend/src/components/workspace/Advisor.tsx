import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  Compass,
  Globe2,
  Plus,
  Search,
  Sparkles,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  api,
  type Campaign,
  type Thread,
  type Workspace,
  active,
} from "../../services/workspaceApi";
import { Mark, Spinner } from "./Shared";
import SearchRun from "./SearchRun";

const starters = [
  {
    icon: <Compass size={19} />,
    title: "Find SEO prospects",
    text: "Help me choose a local business niche for my SEO services.",
  },
  {
    icon: <Globe2 size={19} />,
    title: "Choose the right cities",
    text: "Help me choose similar cities for an SEO outreach campaign.",
  },
  {
    icon: <Search size={19} />,
    title: "Fetch me 50 leads",
    text: "Fetch me 50 leads for SEO outreach. Help me confirm the business niche and cities first.",
  },
];
export default function Advisor({
  workspace,
  refresh,
  review,
  researchAvailable = true,
}: {
  workspace: Workspace;
  refresh: () => Promise<void>;
  review: (campaign: Campaign) => void;
  researchAvailable?: boolean;
}) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const pendingId = useRef<{ text: string; id: string } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [thread?.messages.length, pending]);
  async function select(id: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setThread(await api<Thread>("/threads/" + id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function send(event?: FormEvent, text = message) {
    event?.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    setPending(value);
    if (pendingId.current?.text !== value)
      pendingId.current = { text: value, id: crypto.randomUUID() };
    try {
      const current = thread || (await api<Thread>("/threads", "POST"));
      setThread(current);
      const result = await api<Thread>(
        "/threads/" + current.id + "/messages",
        "POST",
        { message: value, message_id: pendingId.current.id },
      );
      if (mounted.current) {
        setThread(result);
        setMessage("");
        pendingId.current = null;
      }
      await refresh();
    } catch (err) {
      if (mounted.current) setError((err as Error).message);
    } finally {
      if (mounted.current) {
        setPending("");
        setBusy(false);
        input.current?.focus();
      }
    }
  }
  function suggest(text: string) {
    setMessage(text);
    input.current?.focus();
  }
  const attachedIds = new Set(
    thread?.messages.flatMap((item) => item.campaign_ids || []) || [],
  );
  const unattached = workspace.campaigns.filter(
    (campaign) =>
      !attachedIds.has(campaign.id) &&
      (active(campaign) || (thread ? campaign.thread_id === thread.id : true)),
  );
  return (
    <div className="advisor-layout">
      <aside className="research-history">
        <div className="section-label">
          YOUR RESEARCH
          <button
            className="icon-button"
            aria-label="New research conversation"
            disabled={busy}
            onClick={() => {
              setThread(null);
              setMessage("");
              setError("");
            }}
          >
            <Plus size={17} />
          </button>
        </div>
        <button
          className="new-research"
          disabled={busy}
          onClick={() => {
            setThread(null);
            setError("");
          }}
        >
          <Plus size={15} /> New conversation
        </button>
        {workspace.threads.length ? (
          workspace.threads.map((item) => (
            <button
              key={item.id}
              disabled={busy}
              className={
                "history-item " + (item.id === thread?.id ? "selected" : "")
              }
              onClick={() => void select(item.id)}
            >
              <span>{item.title}</span>
            </button>
          ))
        ) : (
          <p className="history-empty">
            Your research conversations will appear here.
          </p>
        )}
        <div className="research-context">
          <Sparkles size={17} />
          <strong>Your business context</strong>
          <p>
            {workspace.profile.offer ||
              "Tell your agent about your SEO offer, preferred business types and service area. Your conversation guides the search."}
          </p>
        </div>
      </aside>
      <section className="advisor-main">
        <div className="advisor-heading">
          <div>
            <Mark small />
            <strong>Research advisor</strong>
            <span className="advisor-status">
              <i /> {busy ? "Working on your request" : "Ready to research"}
            </span>
          </div>
          <select
            className="mobile-conversation-select"
            aria-label="Research conversation"
            value={thread?.id || ""}
            disabled={busy}
            onChange={(event) => {
              if (event.target.value) void select(event.target.value);
              else {
                setThread(null);
                setMessage("");
                setError("");
              }
            }}
          >
            <option value="">New conversation</option>
            {workspace.threads.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
          <span className="subtle">SEO research → people → leads</span>
        </div>
        <div className="advisor-scroll" aria-live="polite">
          {!thread?.messages.length && !pending && (
            <div className="advisor-welcome">
              <div className="welcome-symbol">
                <Sparkles size={28} />
              </div>
              <p className="overline">YOUR NEXT OPPORTUNITY STARTS HERE</p>
              <h1>
                Your next SEO clients.
                <br />
                One conversation away.
              </h1>
              <p>
                Tell me the businesses, cities and number of people you want to
                reach. I’ll find their companies, discover the right contacts
                and check their emails.
              </p>
              <div className="starter-grid">
                {starters.map((item) => (
                  <button
                    key={item.title}
                    onClick={() => {
                      setMessage(item.text);
                      input.current?.focus();
                    }}
                  >
                    {item.icon}
                    <strong>{item.title}</strong>
                    <span>{item.text}</span>
                    <ArrowRight size={15} />
                  </button>
                ))}
              </div>
            </div>
          )}
          {thread?.messages.map((item) => (
            <div key={item.id} className={"advisor-message " + item.role}>
              {item.role === "assistant" ? (
                <Mark small />
              ) : (
                <span className="user-avatar">Y</span>
              )}
              <div className="message-body">
                <div className="message-name">
                  {item.role === "assistant" ? "GenMantis" : "You"}
                  <time>
                    {new Date(item.at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                </div>
                {!!item.traces?.length && (
                  <details className="research-trace">
                    <summary>
                      <Check size={13} />
                      {item.traces.length} research steps
                      <ChevronDown size={13} />
                    </summary>
                    {item.traces.map((trace) => (
                      <div key={trace.id}>
                        <span
                          className={
                            trace.status === "error" ? "trace-failed" : ""
                          }
                        >
                          {trace.status === "error"
                            ? "Could not complete: "
                            : "✓ "}
                          {trace.label}
                        </span>
                        {trace.sources
                          .filter((s) => s.url)
                          .slice(0, 3)
                          .map((source) => (
                            <a
                              key={source.url}
                              href={source.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {source.title || source.url}
                            </a>
                          ))}
                      </div>
                    ))}
                  </details>
                )}
                <div className="markdown">
                  <ReactMarkdown
                    components={{
                      a: ({ children, href }) => (
                        <a href={href} target="_blank" rel="noreferrer">
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {item.content}
                  </ReactMarkdown>
                </div>
                {item.campaign_ids?.map((id) => {
                  const campaign = workspace.campaigns.find((c) => c.id === id);
                  return campaign ? (
                    <SearchRun
                      key={id}
                      campaign={campaign}
                      refresh={refresh}
                      viewLeads={() => review(campaign)}
                      suggest={suggest}
                    />
                  ) : null;
                })}
              </div>
            </div>
          ))}
          {unattached.length > 0 && (
            <section className="advisor-search-history">
              <button
                className="text-link"
                onClick={() => setShowHistory(!showHistory)}
              >
                {showHistory
                  ? "Show recent searches"
                  : `Search history (${unattached.length})`}
              </button>
              {(showHistory ? unattached : unattached.slice(0, 3)).map(
                (campaign) => (
                  <SearchRun
                    key={campaign.id}
                    campaign={campaign}
                    refresh={refresh}
                    viewLeads={() => review(campaign)}
                    suggest={suggest}
                  />
                ),
              )}
            </section>
          )}
          {pending && (
            <div className="advisor-message user">
              <span className="user-avatar">Y</span>
              <div className="message-body">
                <div className="message-name">You</div>
                <p>{pending}</p>
              </div>
            </div>
          )}
          {busy && pending && (
            <div className="advisor-message">
              <Mark small />
              <div className="message-body">
                <Spinner label="Researching your request…" />
                <small className="muted">
                  Understanding your request and choosing the next research
                  step.
                </small>
              </div>
            </div>
          )}
          {error && (
            <p role="alert" className="error-banner">
              {error}
            </p>
          )}
          <div ref={bottom} />
        </div>
        <div className="composer-wrap">
          <form className="advisor-composer" onSubmit={send}>
            <textarea
              ref={input}
              aria-label="Message research advisor"
              value={message}
              maxLength={5000}
              rows={2}
              placeholder="Find me 50 dentist leads in Austin, Round Rock and Cedar Park, Texas…"
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div>
              <span>
                <Globe2 size={13} />{" "}
                {researchAvailable
                  ? "Web research available"
                  : "Research provider not connected"}
              </span>
              <button
                aria-label="Send message"
                disabled={busy || !message.trim()}
              >
                <ArrowUp size={19} />
              </button>
            </div>
          </form>
          <p>
            Ask to fetch leads to start. The agent deepens searches within your
            selected cities until the target or search limits are reached.
          </p>
        </div>
      </section>
    </div>
  );
}
