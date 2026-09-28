import { motion } from "framer-motion";
import { Beaker, Bot, Copy, Database, KeyRound, Power, RefreshCw, RotateCcw, ScrollText, ShieldCheck, TestTubes } from "lucide-react";
import { Button, ErrorCard, SkeletonList, StatusPill, Toggle, useToast } from "../components/ui";
import { api } from "../lib/api";
import { keys, useInvalidateProject, useMutation, usePid, useProject, useQuery, useQueryClient, useStatus } from "../lib/hooks";
import { dateTime, pct } from "../lib/meta";

export default function SettingsPage() {
  const pid = usePid();
  const project = useProject(pid);
  const status = useStatus();
  const bank = useQuery({ queryKey: keys.bank(pid), queryFn: () => api.bank(pid), enabled: !!pid });
  const evals = useQuery({ queryKey: keys.evals(pid), queryFn: () => api.evals(pid), enabled: !!pid });
  const audit = useQuery({ queryKey: keys.audit(pid), queryFn: () => api.audit(pid), enabled: !!pid });
  const invalidate = useInvalidateProject();
  const qc = useQueryClient();
  const toast = useToast();
  const provision = useMutation({ mutationFn: () => api.provision(pid), onSuccess: (r) => { toast.success(`Bank ${r.bank_status}`); invalidate(pid); void qc.invalidateQueries({ queryKey: keys.bank(pid) }); }, onError: (e) => toast.error(e) });
  const offline = useMutation({ mutationFn: (v: boolean) => api.setOffline(v), onSuccess: () => { void qc.invalidateQueries(); }, onError: (e) => toast.error(e) });
  const flush = useMutation({ mutationFn: () => api.flushOutbox(pid), onSuccess: (r) => { toast.success(`Synced ${r.synced}, failed ${r.failed}`); invalidate(pid); }, onError: (e) => toast.error(e) });
  const runEval = useMutation({ mutationFn: () => api.runEval(pid), onSuccess: () => { void qc.invalidateQueries({ queryKey: keys.evals(pid) }); invalidate(pid); }, onError: (e) => toast.error(e) });
  const reset = useMutation({ mutationFn: () => api.resetProject(pid), onSuccess: () => { toast.success("Reset — reseed from the Projects page."); invalidate(pid); }, onError: (e) => toast.error(e) });
  const p = project.data;
  const latest = evals.data?.[0];
  const mcpConfig = JSON.stringify({ mcpServers: { projectpulse: { type: "stdio", command: "<repo>/.venv/bin/python", args: ["<repo>/projectpulse-mcp/server.py"] } } }, null, 2);
  const agentInstructions = `ProjectPulse project ID: ${pid}\n\nBefore implementing a task, call projectpulse_brief with the project ID and the task, and follow the applied records.\nBefore finishing, call projectpulse_check with your code or plan and fix every violation.\nWhen the session ends, call projectpulse_submit_session with the transcript so the team can review new memory.\nNever submit secrets, API keys, passwords or personal data.`;

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head">
        <div><div className="eyebrow">Settings</div><h1>Bank, guardrails and proof</h1><p>Credentials live only in server environment variables — nothing to rotate here.</p></div>
      </div>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <div className="card">
            <div className="card-head"><h3><Database /> Hindsight bank</h3>{p && <StatusPill tone={p.bank_status === "ready" ? "ok" : p.bank_status === "error" ? "bad" : "warn"} label={p.bank_status} live />}</div>
            {!p ? <SkeletonList rows={3} h={20} /> : (
              <dl className="kv">
                <dt>Bank ID</dt><dd>{p.bank_id}</dd>
                <dt>Project ID</dt><dd>{p.id}</dd>
                <dt>Isolation</dt><dd>one bank per project · resolved server-side · <b style={{ color: (p.stats.isolation_violations_blocked ?? 0) ? "var(--red)" : "var(--green)" }}>{p.stats.isolation_violations_blocked ?? 0} violations blocked</b></dd>
                <dt>Extraction mode</dt><dd>{String(bank.data?.config?.retain_extraction_mode ?? "—")}</dd>
                <dt>Observations</dt><dd>{String(bank.data?.config?.enable_observations ?? "—")} (auto-consolidation {String(bank.data?.config?.enable_auto_consolidation ?? "—")})</dd>
                <dt>Memory defense</dt><dd>{bank.data?.config?.memory_defense ? JSON.stringify(bank.data.config.memory_defense) : "not entitled on this plan — ProjectPulse validator redaction applies"}</dd>
                <dt>Retain mission</dt><dd style={{ fontFamily: "var(--sans)" }}>{String(bank.data?.config?.retain_mission ?? "—")}</dd>
                <dt>Reflect mission</dt><dd style={{ fontFamily: "var(--sans)" }}>{String(bank.data?.config?.reflect_mission ?? "—")}</dd>
              </dl>
            )}
            {bank.error && <ErrorCard error={bank.error} />}
            <div className="row" style={{ marginTop: 12 }}>
              <Button size="sm" icon={RefreshCw} loading={provision.isPending} onClick={() => provision.mutate()}>Reprovision (idempotent)</Button>
              <Button size="sm" icon={RotateCcw} loading={flush.isPending} onClick={() => flush.mutate()}>Sync outbox ({p?.stats.unsynced_records ?? 0})</Button>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3><ShieldCheck /> Directives (guardrails on every reflect)</h3></div>
            <div className="list">
              {(bank.data?.directives ?? []).map((d) => <div key={d.name} className="list-item"><ShieldCheck size={15} style={{ color: "var(--green)", flex: "none" }} /><div><div className="small strong">{d.name}</div><div className="small muted">{d.content}</div></div></div>)}
              {!bank.data?.directives.length && <div className="small muted">{bank.isLoading ? "Loading…" : "Unavailable while Hindsight is offline."}</div>}
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3><Power /> Degradation & demo controls</h3>{status.data && <StatusPill tone={status.data.demo_mode ? "violet" : "none"} label={status.data.demo_mode ? "DEMO_MODE" : "production"} />}</div>
            <Toggle on={!!status.data?.force_offline} onChange={(v) => offline.mutate(v)} label="Force Hindsight offline (HINDSIGHT_FORCE_OFFLINE)" />
            <p className="tiny muted">Shows the honest degraded state: Brief/Check/Ask disabled with the reason, approvals queue as “Waiting to sync”, baseline still runs.</p>
            <Button size="sm" variant="danger" icon={RotateCcw} loading={reset.isPending} onClick={() => { if (confirm("Delete this project's records, sessions and runs and recreate its bank?")) reset.mutate(); }}>Reset project data</Button>
          </div>
        </div>
        <div className="stack">
          <div className="card glow">
            <div className="card-head"><h3><TestTubes /> Labelled eval set</h3><Button size="sm" variant="primary" icon={Beaker} loading={runEval.isPending} onClick={() => runEval.mutate()}>Run eval</Button></div>
            <p className="tiny muted">Blueprint §25.4: 10 labelled tasks. Applied-record precision and recall are measured and reported as-is — targets ≥ 0.8, never assumed.</p>
            {latest ? (
              <>
                <div className="grid-3" style={{ margin: "10px 0" }}>
                  <div><div className="tiny muted">Precision</div><div style={{ fontSize: 26, fontWeight: 800 }}>{pct(latest.precision)}</div></div>
                  <div><div className="tiny muted">Recall</div><div style={{ fontSize: 26, fontWeight: 800 }}>{pct(latest.recall)}</div></div>
                  <div><div className="tiny muted">Forbidden-record rate</div><div style={{ fontSize: 26, fontWeight: 800, color: latest.forbidden_rate ? "var(--red)" : "var(--green)" }}>{pct(latest.forbidden_rate)}</div></div>
                </div>
                <div className="tiny faint">{dateTime(latest.created_at)} · filter model {latest.models.small}</div>
                <table className="table" style={{ marginTop: 10 }}>
                  <thead><tr><th>Task</th><th>Applied</th><th>Expected</th><th>P</th><th>R</th></tr></thead>
                  <tbody>{latest.results.map((r) => (
                    <tr key={r.id} style={{ cursor: "default" }}><td className="small"><b>{r.id}</b> {r.task}{r.missing_labels.length ? <div className="tiny faint">missing: {r.missing_labels.join(", ")}</div> : null}{r.forbidden_applied.length ? <div className="tiny" style={{ color: "var(--red)" }}>forbidden: {r.forbidden_applied.join(", ")}</div> : null}</td><td className="mono tiny">{r.applied.join(" ")}</td><td className="mono tiny">{r.expected.join(" ")}</td><td className="mono small">{pct(r.precision)}</td><td className="mono small">{pct(r.recall)}</td></tr>
                  ))}</tbody>
                </table>
              </>
            ) : <div className="small muted">{evals.isLoading ? "Loading…" : "No eval run yet."}</div>}
          </div>
          <div className="card">
            <div className="card-head"><h3><Bot /> Connect a coding agent (MCP)</h3></div>
            <p className="tiny muted">Tools: <code>projectpulse_brief</code>, <code>projectpulse_check</code>, <code>projectpulse_submit_session</code>, <code>projectpulse_ask</code>, <code>projectpulse_rulebook</code> plus recall/retain/list.</p>
            <CopyBlock label=".mcp.json" text={mcpConfig} />
            <CopyBlock label="CLAUDE.md / agent instructions" text={agentInstructions} />
          </div>
          <div className="card">
            <div className="card-head"><h3><ScrollText /> Audit log</h3><span className="tiny faint">Hindsight & LLM calls with latency</span></div>
            <div style={{ maxHeight: 340, overflowY: "auto" }}>
              {(audit.data ?? []).map((e) => (
                <motion.div key={e.id} className="row small" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)", gap: 8 }} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <span className="mono tiny" style={{ width: 170, color: e.status === "ok" ? "var(--teal)" : "var(--red)" }}>{e.event_type}</span>
                  <span className="clip muted" style={{ flex: 1 }}>{summarize(e.detail)}</span>
                  <span className="mono tiny faint">{e.latency_ms != null ? `${e.latency_ms}ms` : ""}</span>
                  <span className="tiny faint nowrap">{dateTime(e.created_at)}</span>
                </motion.div>
              ))}
            </div>
          </div>
          <div className="card tight"><div className="row small"><KeyRound size={14} className="muted" /> Models: <code>{status.data?.models.large}</code> (generate, judge) · <code>{status.data?.models.small}</code> (extract, relate, filter)</div></div>
        </div>
      </div>
    </div>
  );
}

function summarize(detail: Record<string, unknown>): string {
  const keys = ["purpose", "query", "verdict", "resolution", "title", "mode", "error", "dataset", "record_ids"];
  return keys.filter((k) => detail[k] !== undefined && detail[k] !== null && detail[k] !== "").map((k) => `${k}: ${Array.isArray(detail[k]) ? (detail[k] as unknown[]).length : String(detail[k]).slice(0, 80)}`).join(" · ");
}

function CopyBlock({ label, text }: { label: string; text: string }) {
  const toast = useToast();
  return (
    <div style={{ marginTop: 10 }}>
      <div className="row tiny muted" style={{ marginBottom: 4 }}>{label}<span className="spacer" /><button className="btn xs ghost" onClick={() => void navigator.clipboard?.writeText(text).then(() => toast.success("Copied"))}><Copy /> Copy</button></div>
      <pre className="code-block" style={{ padding: 10, fontSize: 11, whiteSpace: "pre-wrap", margin: 0 }}>{text}</pre>
    </div>
  );
}
