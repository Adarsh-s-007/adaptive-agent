import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowDown,
  Ban,
  Database,
  FileText,
  GitCommitVertical,
  History,
  Quote,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { keys, useInvalidateProject, useMutation, usePid, useQuery } from "../lib/hooks";
import { dateTime, shortDate, typeMeta } from "../lib/meta";
import {
  Button,
  CodeBlock,
  ConfidenceBand,
  ErrorCard,
  Modal,
  ProvenancePill,
  RetainState,
  Section,
  SkeletonList,
  StatusPill,
  TypeBadge,
  useToast,
} from "./ui";
import { useRecordDrawer } from "./drawerContext";

export function RecordDrawer() {
  const [params] = useSearchParams();
  const recordId = params.get("record");
  const pid = usePid();
  const close = useRecordDrawer();
  return (
    <AnimatePresence>
      {recordId && pid && (
        <>
          <motion.div className="overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => close(null)} />
          <motion.aside
            className="drawer"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", bounce: 0.08, duration: 0.5 }}
            role="dialog"
            aria-label="Record details"
          >
            <DrawerBody pid={pid} rid={recordId} onClose={() => close(null)} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function DrawerBody({ pid, rid, onClose }: { pid: string; rid: string; onClose: () => void }) {
  const q = useQuery({ queryKey: keys.memory(pid, rid), queryFn: () => api.memory(pid, rid) });
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const [modal, setModal] = useState<"supersede" | "retract" | null>(null);
  const retry = useMutation({
    mutationFn: () => api.retry(pid, rid),
    onSuccess: (r) => { toast.success(r.retain_state === "retained" ? "Synced to Hindsight" : "Still waiting to sync"); invalidate(pid); },
    onError: (e) => toast.error(e),
  });
  const r = q.data;
  const meta = r ? typeMeta(r.type) : null;

  return (
    <>
      <div className="drawer-head">
        <div className="row">
          {r ? <ProvenancePill record={r} /> : <span className="muted">Loading…</span>}
          {r && <TypeBadge type={r.type} />}
          <span className="spacer" />
          <button className="btn icon ghost" onClick={onClose} aria-label="Close"><X /></button>
        </div>
        {r && (
          <>
            <h2 style={{ margin: "12px 0 4px", fontSize: 19, letterSpacing: "-0.02em" }}>{r.title}</h2>
            <div className="row wrap" style={{ gap: 8 }}>
              <StatusPill tone={r.status === "active" ? "ok" : r.status === "superseded" ? "warn" : "bad"} label={r.status} />
              <RetainState state={r.retain_state} />
              {r.review_due && <StatusPill tone="warn" label="Review due" />}
              {r.tentative && <StatusPill tone="warn" label="Tentative" />}
              <ConfidenceBand band={r.confidence_band} />
            </div>
          </>
        )}
      </div>
      <div className="drawer-body">
        {q.isLoading && <SkeletonList rows={5} />}
        {q.error && <ErrorCard error={q.error} onRetry={() => q.refetch()} />}
        {r && meta && (
          <>
            <div className="card tight" style={{ borderColor: `${meta.color}55`, background: `linear-gradient(140deg, ${meta.color}14, rgba(10,13,28,.7))` }}>
              <div className="section-label">Rule</div>
              <div style={{ fontSize: 15, lineHeight: 1.6 }}>{r.statement}</div>
              {r.rationale && (
                <>
                  <div className="section-label" style={{ marginTop: 12 }}>Why</div>
                  <div className="muted">{r.rationale}</div>
                </>
              )}
              {r.applies_to.length > 0 && (
                <div className="row wrap" style={{ marginTop: 12, gap: 6 }}>
                  {r.applies_to.map((a) => <span key={a} className="pill">{a}</span>)}
                </div>
              )}
            </div>

            <div className="row wrap">
              {r.status === "active" && <Button size="sm" icon={Sparkles} onClick={() => setModal("supersede")}>Supersede with new version</Button>}
              {r.status === "active" && <Button size="sm" variant="danger" icon={Ban} onClick={() => setModal("retract")}>Retract</Button>}
              {r.retain_state !== "retained" && <Button size="sm" icon={RefreshCw} loading={retry.isPending} onClick={() => retry.mutate()}>Retry sync</Button>}
            </div>
            {r.last_error && r.retain_state !== "retained" && <div className="callout warn small">{r.last_error}</div>}

            <Section label={<><Quote size={12} /> Evidence ({r.evidence?.length ?? 0})</>}>
              <div className="list">
                {(r.evidence ?? []).map((ev) => (
                  <div key={ev.id} className="quote">
                    “{ev.quote}”
                    <div className="tiny faint" style={{ marginTop: 6 }}>{ev.speaker} · turn {ev.turn_index ?? "—"} · {dateTime(ev.created_at)}</div>
                  </div>
                ))}
                {!r.evidence?.length && <div className="muted small">Manually authored — no transcript quote.</div>}
              </div>
            </Section>

            <Section label={<><History size={12} /> Version chain</>}>
              <div className="timeline" style={{ paddingLeft: 24 }}>
                {(r.version_chain ?? []).map((v) => (
                  <div key={v.id} className="tl-item" style={{ paddingBottom: 12 }}>
                    <span className="tl-node" style={{ borderColor: v.relation === "this" ? "var(--violet)" : v.status === "active" ? "var(--green)" : "var(--red)" }}>
                      {v.relation === "older" ? <ArrowDown /> : <GitCommitVertical />}
                    </span>
                    <div className={`tl-card ${v.status !== "active" ? "" : ""}`} style={v.relation === "this" ? { borderColor: "rgba(141,124,255,.5)" } : undefined}>
                      <div className="row"><ProvenancePill record={v} showArea={false} /><span className="tiny muted">{shortDate(v.decided_at)}</span><span className="spacer" /><span className="tiny faint">{v.relation === "this" ? "this version" : v.status}</span></div>
                      <div className={`small ${v.status !== "active" ? "strike" : ""}`} style={{ marginTop: 6 }}>{v.statement}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Section>

            <div className="grid-2">
              <Section label={<><ShieldCheck size={12} /> Applied in ({r.applied_in?.length ?? 0})</>}>
                <div className="list">
                  {(r.applied_in ?? []).slice(0, 6).map((a) => <div key={a.run_id} className="small muted clip" title={a.task}>• {a.task}</div>)}
                  {!r.applied_in?.length && <div className="small faint">Not applied yet.</div>}
                </div>
              </Section>
              <Section label={<><Ban size={12} /> Violated in ({r.violated_in?.length ?? 0})</>}>
                <div className="list">
                  {(r.violated_in ?? []).slice(0, 6).map((v) => <code key={v.check_id} className="small clip" style={{ color: "#ffb3c1" }}>{v.excerpt}</code>)}
                  {!r.violated_in?.length && <div className="small faint">No violations recorded.</div>}
                </div>
              </Section>
            </div>

            <Section label={<><Database size={12} /> Hindsight document</>}>
              <dl className="kv">
                <dt>Document ID</dt><dd>{r.hindsight_document_id}</dd>
                <dt>Live tags</dt><dd>{r.hindsight_document?.tags?.join("  ") ?? "— (unavailable)"}</dd>
                <dt>Memory units</dt><dd>{r.hindsight_document ? JSON.stringify(r.hindsight_document.nodes_by_fact_type ?? r.hindsight_document.memory_unit_count) : "—"}</dd>
                <dt>Decided</dt><dd>{dateTime(r.decided_at)}</dd>
                <dt>Approved by</dt><dd>{r.approved_by ?? "—"} · {dateTime(r.approved_at)}</dd>
                <dt>Source</dt><dd>{r.source} · stated by {r.stated_by}</dd>
                <dt>Source session</dt><dd>{r.source_session ? r.source_session.title : "—"}</dd>
                <dt>Review due</dt><dd>{shortDate(r.review_due_at)}</dd>
                <dt>Times applied / violated</dt><dd>{r.times_applied} / {r.times_violated}</dd>
              </dl>
            </Section>

            {r.check_patterns.length > 0 && (
              <Section label="Deterministic check patterns (evidence only)">
                <div className="row wrap" style={{ gap: 6 }}>
                  {r.check_patterns.map((p) => <code key={p} className="pill mono" style={{ fontSize: 10.5 }}>{p}</code>)}
                </div>
              </Section>
            )}

            {r.retained_content && (
              <Section label={<><FileText size={12} /> Exact retained content</>}>
                <CodeBlock code={r.retained_content} path={`${r.hindsight_document_id}.txt`} />
              </Section>
            )}
          </>
        )}
      </div>
      {r && (
        <>
          <SupersedeModal open={modal === "supersede"} onClose={() => setModal(null)} pid={pid} rid={rid} base={r} />
          <RetractModal open={modal === "retract"} onClose={() => setModal(null)} pid={pid} rid={rid} pill={r.pill} />
        </>
      )}
    </>
  );
}

function SupersedeModal({ open, onClose, pid, rid, base }: { open: boolean; onClose: () => void; pid: string; rid: string; base: { title: string; statement: string; rationale?: string | null; area?: string | null } }) {
  const [form, setForm] = useState({ title: base.title, statement: base.statement, rationale: base.rationale ?? "", area: base.area ?? "", reviewer: "Tech lead" });
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const open_ = useRecordDrawer();
  const m = useMutation({
    mutationFn: () => api.supersede(pid, rid, form),
    onSuccess: (res) => { toast.success(`${res.superseded_record.pill} superseded by ${res.record.pill}`); invalidate(pid); onClose(); open_(res.record.id); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose}>
      <h2>Supersede with a new version</h2>
      <p className="muted small">Records are immutable. The new version becomes active, the old one is retagged <code>status:superseded</code> in Hindsight and never reaches an agent again. History is kept.</p>
      <div className="stack" style={{ marginTop: 14 }}>
        <label className="field"><span>Title</span><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <label className="field"><span>Rule</span><textarea className="textarea" value={form.statement} onChange={(e) => setForm({ ...form, statement: e.target.value })} /></label>
        <label className="field"><span>Rationale</span><input className="input" value={form.rationale} onChange={(e) => setForm({ ...form, rationale: e.target.value })} /></label>
        <div className="grid-2">
          <label className="field"><span>Area</span><input className="input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} /></label>
          <label className="field"><span>Reviewer</span><input className="input" value={form.reviewer} onChange={(e) => setForm({ ...form, reviewer: e.target.value })} /></label>
        </div>
        <div className="row"><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>Approve new version</Button></div>
      </div>
    </Modal>
  );
}

function RetractModal({ open, onClose, pid, rid, pill }: { open: boolean; onClose: () => void; pid: string; rid: string; pill: string }) {
  const [reason, setReason] = useState("");
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.retract(pid, rid, { reason, reviewer: "Tech lead" }),
    onSuccess: () => { toast.success(`${pill} retracted — removed from recall`); invalidate(pid); onClose(); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose} width={480}>
      <h2>Retract {pill}</h2>
      <p className="muted small">Use when a record was wrong from the start. It is removed from recall without a replacement.</p>
      <label className="field" style={{ marginTop: 12 }}><span>Reason</span><textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why was this wrong?" /></label>
      <div className="row" style={{ marginTop: 14 }}><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="danger" loading={m.isPending} disabled={reason.trim().length < 3} onClick={() => m.mutate()}>Retract record</Button></div>
    </Modal>
  );
}
