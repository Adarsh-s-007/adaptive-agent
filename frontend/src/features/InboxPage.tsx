import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check, ChevronDown, Edit3, Filter, Inbox, ShieldAlert, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, ConfidenceBand, EmptyState, ErrorCard, Kbd, Modal, ProvenancePill, SkeletonList, StatusPill, TypeBadge, useToast } from "../components/ui";
import { api, type Candidate } from "../lib/api";
import { useInbox, useInvalidateProject, useMutation, usePid } from "../lib/hooks";
import { dateTime, MEMORY_TYPES, typeMeta } from "../lib/meta";

const RELATION_LABEL: Record<Candidate["relation"], { label: string; tone: "ok" | "warn" | "bad" | "info" | "violet" }> = {
  new: { label: "new", tone: "ok" },
  duplicate: { label: "already known", tone: "info" },
  refines: { label: "refines", tone: "violet" },
  conflicts: { label: "conflicts", tone: "bad" },
  supersedes: { label: "supersedes", tone: "warn" },
};

export default function InboxPage() {
  const pid = usePid();
  const inbox = useInbox(pid);
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const [reviewer, setReviewer] = useState(() => localStorage.getItem("pp.reviewer") ?? "Priya Raman");
  const [focus, setFocus] = useState(0);
  const [editing, setEditing] = useState<Candidate | null>(null);
  useEffect(() => { try { localStorage.setItem("pp.reviewer", reviewer); } catch { /* ignore */ } }, [reviewer]);

  const pending = useMemo(() => (inbox.data?.groups ?? []).flatMap((g) => g.pending), [inbox.data]);
  const approve = useMutation({
    mutationFn: ({ c, resolution, edits }: { c: Candidate; resolution?: string; edits?: Record<string, unknown> }) =>
      api.approve(pid, c.id, { reviewer, resolution, target_record_id: c.related_record_id, edits }),
    onSuccess: (res) => {
      const pill = res.record?.pill;
      toast.success(
        res.resolution === "add_evidence" ? `Added as evidence to ${pill} — no duplicate retained.`
          : res.superseded_record ? `${pill} approved; ${res.superseded_record.pill} superseded and retagged in Hindsight.`
          : `${pill} approved and retained into the project's Hindsight bank.`,
      );
      invalidate(pid);
      setEditing(null);
    },
    onError: (e) => toast.error(e),
  });
  const reject = useMutation({
    mutationFn: (c: Candidate) => api.reject(pid, c.id, { reviewer, reason: "Rejected by reviewer" }),
    onSuccess: () => { toast.info("Rejected — never enters memory."); invalidate(pid); },
    onError: (e) => toast.error(e),
  });
  const bulk = useMutation({
    mutationFn: () => api.approveHighConfidence(pid, reviewer),
    onSuccess: (r) => { toast.success(`Approved ${r.approved} high-confidence new candidates.`); invalidate(pid); },
    onError: (e) => toast.error(e),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (editing || (e.target as HTMLElement)?.closest("input,textarea,select")) return;
      const c = pending[focus];
      if (e.key === "j" || e.key === "ArrowDown") setFocus((f) => Math.min(pending.length - 1, f + 1));
      else if (e.key === "k" || e.key === "ArrowUp") setFocus((f) => Math.max(0, f - 1));
      else if (!c) return;
      else if (e.key.toLowerCase() === "a" && !c.flagged) approve.mutate({ c });
      else if (e.key.toLowerCase() === "e") setEditing(c);
      else if (e.key.toLowerCase() === "r") reject.mutate(c);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, focus, editing, approve, reject]);
  useEffect(() => { if (focus >= pending.length) setFocus(Math.max(0, pending.length - 1)); }, [pending.length, focus]);

  const counts = inbox.data?.counts;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Memory inbox</div>
          <h1>Turn candidates into memory</h1>
          <p>Extraction is automatic, approval is human. Every candidate carries the verbatim quote it came from; nothing reaches the Hindsight bank unreviewed.</p>
        </div>
        <div className="row wrap">
          <label className="field" style={{ minWidth: 200 }}><span>Reviewer</span><input className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
          <Button icon={Sparkles} loading={bulk.isPending} disabled={!pending.some((c) => c.relation === "new" && c.confidence >= 0.75 && !c.flagged)} onClick={() => bulk.mutate()}>Approve all new high-confidence</Button>
        </div>
      </div>
      <div className="row wrap tiny muted" style={{ gap: 14 }}>
        <span><b style={{ color: "var(--text)" }}>{counts?.pending ?? 0}</b> pending</span>
        <span><b style={{ color: "var(--text)" }}>{counts?.filtered ?? 0}</b> filtered by validator/extractor</span>
        <span><b style={{ color: "var(--text)" }}>{counts?.reviewed ?? 0}</b> reviewed</span>
        <span className="spacer" />
        <span className="row" style={{ gap: 6 }}><Kbd>A</Kbd> approve <Kbd>E</Kbd> edit <Kbd>R</Kbd> reject <Kbd>J</Kbd>/<Kbd>K</Kbd> move</span>
      </div>
      {inbox.isLoading && <SkeletonList rows={3} h={180} />}
      {inbox.error && <ErrorCard error={inbox.error} onRetry={() => inbox.refetch()} />}
      {inbox.data && inbox.data.groups.length === 0 && (
        <EmptyState icon={Inbox} title="Inbox zero" action={<Link to={`/p/${pid}/workspace`}><Button variant="primary">Open the Workspace</Button></Link>}>
          Candidates appear here when a session ends. Import a transcript or end a Workspace session to extract memory.
        </EmptyState>
      )}
      {(inbox.data?.groups ?? []).map((g) => (
        <div key={g.session.id} className="stack" style={{ gap: 10 }}>
          <div className="row">
            <span className="section-label" style={{ margin: 0 }}>Session</span>
            <Link to={`/p/${pid}/workspace/${g.session.id}`} className="strong small">{g.session.title}</Link>
            <span className="tiny faint">{g.session.developer} · {dateTime(g.session.occurred_at)}</span>
          </div>
          <AnimatePresence>
            {g.pending.map((c) => {
              const idx = pending.indexOf(c);
              return (
                <motion.div key={c.id} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 60, height: 0, marginBottom: -10 }} transition={{ duration: 0.35 }} onClick={() => setFocus(idx)}>
                  <CandidateCard c={c} focused={idx === focus} busy={approve.isPending || reject.isPending}
                    onApprove={(resolution) => approve.mutate({ c, resolution })} onEdit={() => setEditing(c)} onReject={() => reject.mutate(c)} />
                </motion.div>
              );
            })}
          </AnimatePresence>
          {g.filtered.length > 0 && <FilteredRow items={g.filtered} />}
        </div>
      ))}
      {editing && <EditModal c={editing} busy={approve.isPending} onClose={() => setEditing(null)} onSave={(edits) => approve.mutate({ c: editing, edits })} />}
    </div>
  );
}

function highlightQuote(quote: string) {
  return <span className="quote" style={{ display: "block" }}>“<mark>{quote}</mark>”</span>;
}

function CandidateCard({ c, focused, busy, onApprove, onEdit, onReject }: { c: Candidate; focused: boolean; busy: boolean; onApprove: (resolution?: string) => void; onEdit: () => void; onReject: () => void }) {
  const rel = RELATION_LABEL[c.relation];
  const meta = typeMeta(c.type);
  return (
    <div className={`cand ${focused ? "focused" : ""}`} style={{ boxShadow: focused ? undefined : `inset 3px 0 0 ${meta.color}` }}>
      <div className="cand-body">
        <div className="row wrap" style={{ gap: 8 }}>
          <TypeBadge type={c.type} />
          {c.area && <span className="pill">{c.area}</span>}
          <StatusPill tone={rel.tone} label={rel.label} />
          <ConfidenceBand band={c.confidence_band} />
          <span className="pill">stated by {c.stated_by}</span>
          {c.flags.includes("agent_proposed") && <StatusPill tone="warn" label="agent-proposed" />}
          {c.flagged && <StatusPill tone="bad" icon={ShieldAlert} label="instruction-like — edit required" />}
          <span className="spacer" />
          <span className="tiny faint mono">{c.extractor_model}</span>
        </div>
        <div>
          <div className="strong" style={{ fontSize: 15.5 }}>{c.title}</div>
          <div style={{ marginTop: 4, lineHeight: 1.6 }}>{c.statement}</div>
          {c.rationale && <div className="small muted" style={{ marginTop: 4 }}>Why: {c.rationale}</div>}
        </div>
        {highlightQuote(c.evidence_quote)}
        {c.related_record && (
          <div className="relation">
            <div className="list-item" style={{ display: "block" }}>
              <div className="section-label">Existing record</div>
              <div className="row"><ProvenancePill record={c.related_record} /></div>
              <div className={`small ${c.relation === "supersedes" ? "strike" : ""}`} style={{ marginTop: 6 }}>{c.related_record.statement}</div>
            </div>
            <div className="arrow"><ArrowRight /></div>
            <div className="list-item" style={{ display: "block", borderColor: "rgba(67,220,200,.4)" }}>
              <div className="section-label">This candidate</div>
              <div className="small">{c.statement}</div>
              {c.relation_reason && <div className="tiny muted" style={{ marginTop: 6 }}>{c.relation_reason}</div>}
            </div>
          </div>
        )}
      </div>
      <div className="cand-foot">
        {c.relation === "duplicate" ? (
          <Button size="sm" variant="success" icon={Check} disabled={busy} onClick={() => onApprove("add_evidence")}>Add as evidence <Kbd>A</Kbd></Button>
        ) : c.relation === "supersedes" || c.relation === "refines" ? (
          <>
            <Button size="sm" variant="success" icon={Check} disabled={busy || c.flagged} onClick={() => onApprove("supersede")}>Approve as replacement <Kbd>A</Kbd></Button>
            <Button size="sm" disabled={busy || c.flagged} onClick={() => onApprove("keep_both")}>Keep both</Button>
          </>
        ) : c.relation === "conflicts" ? (
          <>
            <Button size="sm" variant="success" icon={Check} disabled={busy || c.flagged} onClick={() => onApprove("supersede")}>Supersede old</Button>
            <Button size="sm" disabled={busy || c.flagged} onClick={() => onApprove("keep_both")}>Keep both (narrow scopes)</Button>
          </>
        ) : (
          <Button size="sm" variant="success" icon={Check} disabled={busy || c.flagged} onClick={() => onApprove("new")}>Approve <Kbd>A</Kbd></Button>
        )}
        <Button size="sm" icon={Edit3} disabled={busy} onClick={onEdit}>Edit then approve <Kbd>E</Kbd></Button>
        <Button size="sm" variant="danger" icon={X} disabled={busy} onClick={onReject}>Reject <Kbd>R</Kbd></Button>
        <span className="spacer" />
        <span className="tiny faint">turns {c.evidence_turn_ids.join(", ") || "—"}</span>
      </div>
    </div>
  );
}

function FilteredRow({ items }: { items: Candidate[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card tight" style={{ background: "rgba(8,10,22,.55)" }}>
      <button className="btn sm ghost" onClick={() => setOpen(!open)}>
        <Filter /> Filtered by validator ({items.length}) <ChevronDown style={{ transform: open ? "rotate(180deg)" : undefined, transition: "transform .2s" }} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="list" style={{ marginTop: 8 }} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
            {items.map((f) => (
              <div key={f.id} className="row small" style={{ gap: 10, alignItems: "flex-start" }}>
                <X size={14} style={{ color: "var(--red)", marginTop: 3, flex: "none" }} />
                <div style={{ minWidth: 0 }}>
                  <div className="clip" style={{ color: "var(--text-2)" }}>{f.statement}</div>
                  <div className="tiny muted">{f.filter_reason}</div>
                </div>
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function EditModal({ c, busy, onClose, onSave }: { c: Candidate; busy: boolean; onClose: () => void; onSave: (edits: Record<string, unknown>) => void }) {
  const [form, setForm] = useState({ title: c.title, statement: c.statement, rationale: c.rationale ?? "", type: c.type, area: c.area ?? "", importance: c.importance });
  return (
    <Modal open onClose={onClose}>
      <h2>Edit then approve</h2>
      <p className="muted small">The quote stays as evidence. {c.flagged && <b style={{ color: "var(--red)" }}>This candidate contained instruction-like text — rewrite it as an engineering rule.</b>}</p>
      <div className="stack" style={{ marginTop: 12 }}>
        <label className="field"><span>Title</span><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <label className="field"><span>Rule</span><textarea className="textarea" value={form.statement} onChange={(e) => setForm({ ...form, statement: e.target.value })} /></label>
        <label className="field"><span>Rationale</span><input className="input" value={form.rationale} onChange={(e) => setForm({ ...form, rationale: e.target.value })} /></label>
        <div className="grid-3">
          <label className="field"><span>Type</span><select className="select" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as Candidate["type"] })}>{MEMORY_TYPES.map((t) => <option key={t} value={t}>{typeMeta(t).label}</option>)}</select></label>
          <label className="field"><span>Area</span><input className="input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} /></label>
          <label className="field"><span>Importance</span><select className="select" value={form.importance} onChange={(e) => setForm({ ...form, importance: Number(e.target.value) })}><option value={1}>1 · low</option><option value={2}>2 · normal</option><option value={3}>3 · critical</option></select></label>
        </div>
        <div className="quote small">“{c.evidence_quote}”</div>
        <div className="row"><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={() => onSave(form)}>Approve edited</Button></div>
      </div>
    </Modal>
  );
}
