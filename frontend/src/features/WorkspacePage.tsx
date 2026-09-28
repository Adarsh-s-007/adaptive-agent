import { motion } from "framer-motion";
import {
  Bot,
  BookmarkPlus,
  FileUp,
  MessageSquarePlus,
  Radar,
  Send,
  Sparkles,
  Square,
  TerminalSquare,
  User,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { RecallPanel } from "../components/RecallPanel";
import { Button, CodeBlock, EmptyState, ErrorCard, Modal, SkeletonList, StatusPill, Toggle, useToast } from "../components/ui";
import { api, type Brief, type Candidate, type Turn } from "../lib/api";
import { keys, useInvalidateProject, useMutation, usePid, useQuery, useQueryClient, useStatus } from "../lib/hooks";
import { dateTime, MEMORY_TYPES, timeAgo, typeMeta } from "../lib/meta";

export default function WorkspacePage() {
  const pid = usePid();
  const { sid } = useParams();
  const navigate = useNavigate();
  const sessions = useQuery({ queryKey: keys.sessions(pid), queryFn: () => api.sessions(pid), enabled: !!pid });
  const [modal, setModal] = useState<"new" | "import" | null>(null);

  useEffect(() => {
    if (!sid && sessions.data?.length) {
      const preferred = sessions.data.find((s) => s.status === "open") ?? sessions.data.find((s) => s.source === "import" && s.status !== "extracted") ?? sessions.data[0];
      navigate(`/p/${pid}/workspace/${preferred.id}`, { replace: true });
    }
  }, [sid, sessions.data, navigate, pid]);

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Agent workspace</div>
          <h1>Where sessions happen and memory forms</h1>
          <p>Work with a memory-aware agent, import a transcript from any coding agent, and end a session to extract reviewed memory candidates automatically.</p>
        </div>
        <div className="row">
          <Button icon={FileUp} onClick={() => setModal("import")}>Import transcript</Button>
          <Button variant="primary" icon={MessageSquarePlus} onClick={() => setModal("new")}>New session</Button>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "260px minmax(0,1fr) 360px", gap: 16, alignItems: "start" }} className="ws-grid">
        <div className="card flush" style={{ position: "sticky", top: 76 }}>
          <div className="card-head" style={{ padding: "14px 14px 0" }}><h3><TerminalSquare /> Sessions</h3><span className="tiny faint">{sessions.data?.length ?? 0}</span></div>
          <div style={{ maxHeight: "70vh", overflowY: "auto", padding: 8 }}>
            {sessions.isLoading && <SkeletonList rows={5} h={52} />}
            {sessions.data?.length === 0 && <div className="muted small" style={{ padding: 10 }}>No sessions yet.</div>}
            {(sessions.data ?? []).map((s) => (
              <Link key={s.id} to={`/p/${pid}/workspace/${s.id}`} className="list-item clickable" style={{ marginBottom: 6, borderColor: s.id === sid ? "var(--violet)" : undefined, background: s.id === sid ? "rgba(141,124,255,.1)" : undefined, display: "block" }}>
                <div className="row" style={{ gap: 6 }}>
                  <span className="small strong clip" style={{ flex: 1 }}>{s.title}</span>
                  {s.pending_candidates ? <span className="nav-badge" style={{ height: 18, minWidth: 18, fontSize: 10 }}>{s.pending_candidates}</span> : null}
                </div>
                <div className="row tiny faint" style={{ marginTop: 3, gap: 6 }}>
                  <span className={`dot`} style={{ width: 6, height: 6, borderRadius: 6, background: s.status === "open" ? "var(--green)" : s.status === "extracted" ? "var(--violet)" : "var(--amber)" }} />
                  {s.status} · {s.developer ?? "—"} · {timeAgo(s.occurred_at)}
                </div>
              </Link>
            ))}
          </div>
        </div>
        {sid ? <SessionView pid={pid} sid={sid} /> : <div className="card"><EmptyState icon={TerminalSquare} title="Start a session">Create a session to work with the memory-aware agent, or import a transcript from Claude Code, Cursor or Codex.</EmptyState></div>}
      </div>
      <NewSessionModal open={modal === "new"} onClose={() => setModal(null)} pid={pid} />
      <ImportModal open={modal === "import"} onClose={() => setModal(null)} pid={pid} />
      <style>{`@media (max-width: 1280px){.ws-grid{grid-template-columns:220px minmax(0,1fr)!important}.ws-grid>:last-child{grid-column:1/-1}}@media (max-width: 860px){.ws-grid{grid-template-columns:1fr!important}}`}</style>
    </div>
  );
}

function SessionView({ pid, sid }: { pid: string; sid: string }) {
  const session = useQuery({ queryKey: keys.session(pid, sid), queryFn: () => api.session(pid, sid), enabled: !!sid });
  const status = useStatus();
  const qc = useQueryClient();
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const [text, setText] = useState("");
  const [useMemory, setUseMemory] = useState(true);
  const [liveBrief, setLiveBrief] = useState<Brief | null>(null);
  const [pendingHuman, setPendingHuman] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<{ candidates: Candidate[]; filtered: Candidate[]; stats: Record<string, unknown> } | null>(null);
  const [remember, setRemember] = useState<Turn | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const llmReady = status.data?.llm.status === "ok";
  const s = session.data;

  useEffect(() => { setLiveBrief(null); setExtraction(null); }, [sid]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [s?.turns?.length, pendingHuman]);

  const lastBrief = useMemo(() => {
    if (liveBrief) return liveBrief;
    const turns = s?.turns ?? [];
    for (let i = turns.length - 1; i >= 0; i--) if (turns[i].run?.brief) return turns[i].run!.brief;
    return null;
  }, [s, liveBrief]);

  const preview = useMutation({
    mutationFn: (content: string) => api.brief(pid, content),
    onSuccess: (b) => setLiveBrief(b),
    onError: (e) => toast.error(e),
  });
  const send = useMutation({
    mutationFn: (content: string) => api.sendMessage(pid, sid, { content, use_memory: useMemory }),
    onMutate: (content) => { setPendingHuman(content); setText(""); },
    onSuccess: (res) => {
      setLiveBrief(res.brief);
      if (res.error) toast.error(`${res.error.code}: ${res.error.message}`);
      void qc.invalidateQueries({ queryKey: keys.session(pid, sid) });
    },
    onError: (e, content) => { toast.error(e); setText(content); },
    onSettled: () => setPendingHuman(null),
  });
  const end = useMutation({
    mutationFn: () => (s?.status === "open" ? api.closeSession(pid, sid) : api.extractSession(pid, sid)),
    onSuccess: (res) => {
      setExtraction(res);
      invalidate(pid);
      toast.success(`Extraction proposed ${res.candidates.length} candidate${res.candidates.length === 1 ? "" : "s"} and filtered ${res.filtered.length}.`);
    },
    onError: (e) => toast.error(e),
  });

  if (session.isLoading) return <div className="card"><SkeletonList rows={6} h={60} /></div>;
  if (session.error) return <ErrorCard error={session.error} onRetry={() => session.refetch()} />;
  if (!s) return null;

  return (
    <>
      <div className="card" style={{ minHeight: 560, display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="row wrap">
          <div style={{ minWidth: 0 }}>
            <div className="strong" style={{ fontSize: 16 }}>{s.title}</div>
            <div className="tiny faint">{s.developer} · {s.agent_label} · {dateTime(s.occurred_at)} · {s.source}</div>
          </div>
          <span className="spacer" />
          <StatusPill tone={s.status === "open" ? "ok" : s.status === "extracted" ? "violet" : "warn"} label={s.status} live={s.status === "open"} />
          <Button size="sm" variant={s.status === "extracted" ? undefined : "primary"} icon={s.status === "open" ? Square : Sparkles} loading={end.isPending} onClick={() => end.mutate()}>
            {s.status === "open" ? "End session & extract" : s.status === "extracted" ? "Re-run extraction" : "Extract memories"}
          </Button>
        </div>
        {s.extraction_error && <div className="callout bad small">Extraction failed: {s.extraction_error}. No partial candidates were saved — retry.</div>}
        {end.isPending && (
          <div className="callout" style={{ position: "relative", overflow: "hidden" }}>
            <div className="scanline" />
            <strong>Extracting…</strong> <span className="muted small">preparing turns → flagging signals → extracting typed candidates → validating verbatim evidence → relating to existing memory</span>
          </div>
        )}
        {extraction && <ExtractionSummary pid={pid} data={extraction} />}

        <div className="chat" style={{ flex: 1 }}>
          {(s.turns ?? []).length === 0 && !pendingHuman && (
            <EmptyState icon={Bot} title="A fresh session">Describe a task. With “Use project memory” on, ProjectPulse recalls the decisions that apply before the agent writes code.</EmptyState>
          )}
          {(s.turns ?? []).map((t) => <Message key={t.id} turn={t} onRemember={() => setRemember(t)} />)}
          {pendingHuman && (
            <>
              <Message turn={{ id: "pending", seq: 0, role: "human", content: pendingHuman, meta: {}, created_at: new Date().toISOString(), speaker: s.developer }} />
              <div className="msg agent"><div className="avatar"><Bot size={15} /></div><div className="bubble"><div className="meta">{useMemory ? "Recalling project memory, filtering, generating…" : "Generating without memory…"}</div><div className="typing"><span /><span /><span /></div></div></div>
            </>
          )}
          <div ref={bottom} />
        </div>

        {s.status === "open" ? (
          <div className="card tight" style={{ background: "rgba(6,8,18,.7)" }}>
            <textarea
              className="textarea"
              style={{ border: 0, background: "transparent", boxShadow: "none", minHeight: 70 }}
              placeholder={llmReady ? "Describe the task… (Ctrl+Enter to send)" : "Describe a task and Preview brief — sending needs GROQ_API_KEY on the server."}
              value={text}
              disabled={send.isPending}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && text.trim().length > 2) send.mutate(text.trim()); }}
            />
            <div className="row">
              <Toggle on={useMemory} onChange={setUseMemory} label="Use project memory" />
              <span className="spacer" />
              <Button icon={Radar} loading={preview.isPending} disabled={text.trim().length < 3} onClick={() => preview.mutate(text.trim())} title="Recall + applicability only — no generation">Preview brief</Button>
              <Button variant="primary" icon={Send} loading={send.isPending} disabled={!llmReady || text.trim().length < 3} onClick={() => send.mutate(text.trim())}>Send</Button>
            </div>
          </div>
        ) : (
          <div className="tiny faint">This session is {s.status}. Its transcript is kept in PostgreSQL for provenance — never retained into Hindsight.</div>
        )}
      </div>

      <div className="card" style={{ position: "sticky", top: 76 }}>
        <div className="card-head"><h3><Radar /> Recall panel</h3><span className="tiny faint">last turn</span></div>
        <RecallPanel brief={lastBrief} />
      </div>
      {remember && <RememberModal pid={pid} sid={sid} turn={remember} onClose={() => setRemember(null)} />}
    </>
  );
}

function Message({ turn, onRemember }: { turn: Turn; onRemember?: () => void }) {
  const Icon = turn.role === "agent" ? Bot : turn.role === "tool" ? Wrench : User;
  const files = turn.run?.files ?? [];
  const content = turn.role === "agent" && files.length ? turn.content.split("\n**")[0] : turn.content;
  const applied = (turn.meta?.applied as string[] | undefined) ?? [];
  return (
    <motion.div className={`msg ${turn.role}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <div className="avatar"><Icon size={15} /></div>
      <div className="bubble">
        <div className="meta">
          <span className="strong" style={{ color: "var(--text-2)" }}>{turn.speaker ?? turn.role}</span>
          <span>#{turn.seq}</span>
          {turn.run && <StatusPill tone={turn.run.mode === "memory" ? "violet" : "none"} label={turn.run.mode === "memory" ? `memory · ${turn.run.brief?.applied.length ?? 0} applied` : "no memory"} />}
          {applied.length > 0 && <span className="tiny mono faint">{applied.join(" ")}</span>}
          <span className="spacer" />
          {onRemember && turn.role !== "tool" && <button className="btn xs ghost" onClick={onRemember} title="Remember this"><BookmarkPlus /> Remember</button>}
        </div>
        <div className="text">{renderText(content)}</div>
        {files.map((f) => <div key={f.path} style={{ marginTop: 10 }}><CodeBlock code={f.content} path={f.path} language={f.language} /></div>)}
        {turn.run?.notes?.length ? <ul className="small muted" style={{ margin: "8px 0 0", paddingLeft: 18 }}>{turn.run.notes.map((n, i) => <li key={i}>{n}</li>)}</ul> : null}
      </div>
    </motion.div>
  );
}

function renderText(text: string) {
  const parts = text.split(/```(\w+)?\n([\s\S]*?)```/g);
  const out: React.ReactNode[] = [];
  for (let i = 0; i < parts.length; i += 3) {
    if (parts[i]) out.push(<span key={`t${i}`}>{parts[i]}</span>);
    if (parts[i + 2] !== undefined) out.push(<div key={`c${i}`} style={{ margin: "8px 0" }}><CodeBlock code={parts[i + 2]} language={parts[i + 1]} /></div>);
  }
  return out;
}

function ExtractionSummary({ pid, data }: { pid: string; data: { candidates: Candidate[]; filtered: Candidate[]; stats: Record<string, unknown> } }) {
  return (
    <motion.div className="callout" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
      <div className="row wrap">
        <Sparkles size={16} style={{ color: "var(--teal)" }} />
        <strong>{data.candidates.length} candidates</strong>
        <span className="muted small">· filtered {data.filtered.length} · extractor {String(data.stats.extractor ?? "—")} · {String(data.stats.latency_ms ?? "—")} ms</span>
        <span className="spacer" />
        <Link to={`/p/${pid}/inbox`}><Button size="sm" variant="primary">Review in Inbox →</Button></Link>
      </div>
      <div className="list" style={{ marginTop: 10 }}>
        {data.candidates.map((c) => (
          <div key={c.id} className="row small" style={{ gap: 8 }}>
            <span className="pill" style={{ color: typeMeta(c.type).color }}>{typeMeta(c.type).label}</span>
            <span className="clip" style={{ flex: 1 }}>{c.title}</span>
            <span className="pill">{c.relation}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

function NewSessionModal({ open, onClose, pid }: { open: boolean; onClose: () => void; pid: string }) {
  const [form, setForm] = useState({ title: "", developer: "Daniel Okafor", agent_label: "ProjectPulse agent" });
  const navigate = useNavigate();
  const invalidate = useInvalidateProject();
  const m = useMutation({
    mutationFn: () => api.createSession(pid, form),
    onSuccess: (s) => { invalidate(pid); onClose(); navigate(`/p/${pid}/workspace/${s.id}`); },
  });
  return (
    <Modal open={open} onClose={onClose} width={520}>
      <h2>New session</h2>
      <div className="stack" style={{ marginTop: 14 }}>
        <label className="field"><span>Title</span><input className="input" autoFocus value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Login flow" /></label>
        <div className="grid-2">
          <label className="field"><span>Developer</span><input className="input" value={form.developer} onChange={(e) => setForm({ ...form, developer: e.target.value })} /></label>
          <label className="field"><span>Agent</span><input className="input" value={form.agent_label} onChange={(e) => setForm({ ...form, agent_label: e.target.value })} /></label>
        </div>
        {m.error && <ErrorCard error={m.error} />}
        <div className="row"><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} disabled={form.title.trim().length < 2} onClick={() => m.mutate()}>Start</Button></div>
      </div>
    </Modal>
  );
}

function ImportModal({ open, onClose, pid }: { open: boolean; onClose: () => void; pid: string }) {
  const [form, setForm] = useState({ title: "", developer: "Developer", agent_label: "Claude Code", text: "", format: "markdown" });
  const navigate = useNavigate();
  const invalidate = useInvalidateProject();
  const m = useMutation({
    mutationFn: () => api.importSession(pid, form),
    onSuccess: (r) => { invalidate(pid); onClose(); navigate(`/p/${pid}/workspace/${r.session_id}`); },
  });
  const onFile = async (file: File) => {
    const text = await file.text();
    const format = file.name.endsWith(".jsonl") || file.name.endsWith(".json") ? "jsonl" : file.name.endsWith(".txt") ? "plain" : "markdown";
    setForm((f) => ({ ...f, text, format, title: f.title || file.name.replace(/\.\w+$/, "") }));
  };
  return (
    <Modal open={open} onClose={onClose} width={760}>
      <h2>Import a transcript</h2>
      <p className="muted small">Paste or upload a session from any coding agent (.md, .txt, .jsonl — Claude Code and OpenAI chat exports are understood). Speaker prefixes map to human, agent and tool. Up to 200k characters; secrets are redacted before extraction.</p>
      <div className="stack" style={{ marginTop: 12 }}>
        <div className="grid-3">
          <label className="field"><span>Title</span><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label className="field"><span>Developer</span><input className="input" value={form.developer} onChange={(e) => setForm({ ...form, developer: e.target.value })} /></label>
          <label className="field"><span>Format</span>
            <select className="select" value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })}>
              <option value="markdown">Markdown</option><option value="jsonl">JSONL</option><option value="plain">Plain text</option>
            </select>
          </label>
        </div>
        <label className="btn sm" style={{ justifySelf: "start" }}><FileUp /> Choose file<input type="file" accept=".md,.txt,.jsonl,.json" hidden onChange={(e) => e.target.files?.[0] && void onFile(e.target.files[0])} /></label>
        <textarea className="textarea code" style={{ minHeight: 240 }} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} placeholder={"Human (Priya): No — we never keep tokens in localStorage…\nAgent: Understood…"} />
        {m.error && <ErrorCard error={m.error} />}
        <div className="row"><span className="tiny faint">{form.text.length.toLocaleString()} / 200,000</span><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} disabled={form.text.trim().length < 10 || form.title.trim().length < 2} onClick={() => m.mutate()}>Import</Button></div>
      </div>
    </Modal>
  );
}

function RememberModal({ pid, sid, turn, onClose }: { pid: string; sid: string; turn: Turn; onClose: () => void }) {
  const firstSentence = turn.content.split(/(?<=[.!?])\s/)[0].slice(0, 380);
  const [form, setForm] = useState({ title: firstSentence.slice(0, 70), statement: firstSentence, type: "decision", area: "", quote: firstSentence, reviewer: turn.speaker ?? "Developer" });
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.remember(pid, sid, turn.id, form),
    onSuccess: (r) => { toast.success(`${r.pill} retained — human-authored, confidence 1.0.`); invalidate(pid); onClose(); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open onClose={onClose}>
      <h2>Remember this</h2>
      <p className="muted small">Creates a human-authored record (confidence 1.0) with this message as evidence. It is retained into the project's Hindsight bank immediately.</p>
      <div className="stack" style={{ marginTop: 12 }}>
        <label className="field"><span>Title</span><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <label className="field"><span>Rule (imperative, 15–400 chars)</span><textarea className="textarea" value={form.statement} onChange={(e) => setForm({ ...form, statement: e.target.value })} /></label>
        <div className="grid-2">
          <label className="field"><span>Type</span>
            <select className="select" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {MEMORY_TYPES.map((t) => <option key={t} value={t}>{typeMeta(t).label}</option>)}
            </select>
          </label>
          <label className="field"><span>Area</span><input className="input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} placeholder="auth, payments…" /></label>
        </div>
        <label className="field"><span>Evidence quote (copied from the message)</span><input className="input" value={form.quote} onChange={(e) => setForm({ ...form, quote: e.target.value })} /></label>
        <div className="row"><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>Retain</Button></div>
      </div>
    </Modal>
  );
}


