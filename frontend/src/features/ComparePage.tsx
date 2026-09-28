import { diffLines } from "diff";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Brain,
  CheckCircle2,
  Circle,
  CircleDashed,
  Columns2,
  FileDiff,
  GitCompareArrows,
  History,
  Loader2,
  Play,
  Radar,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { RecallPanel } from "../components/RecallPanel";
import { AnimatedNumber, Button, CodeBlock, EmptyState, ErrorCard, ProvenancePill, Segmented, StatusPill, useToast } from "../components/ui";
import { api, streamComparison, type CheckResult, type CompareResult, type TaskRun } from "../lib/api";
import { keys, useDemoTasks, useInvalidateProject, usePid, useQuery, useStatus } from "../lib/hooks";
import { emitScene } from "../three/bus";
import { ms, timeAgo } from "../lib/meta";

const STAGES = [
  { key: "queued", label: "Queued" },
  { key: "brief_done", label: "Recall + applicability" },
  { key: "baseline_done", label: "Baseline generated" },
  { key: "memory_done", label: "Memory-aware generated" },
  { key: "checks_done", label: "Blind Memory Check" },
];

export default function ComparePage() {
  const pid = usePid();
  const demo = useDemoTasks();
  const status = useStatus();
  const toast = useToast();
  const invalidate = useInvalidateProject();
  const history = useQuery({ queryKey: keys.comparisons(pid), queryFn: () => api.comparisons(pid), enabled: !!pid });
  const [task, setTask] = useState("Add a POST /api/auth/login route and the client code that keeps the user signed in across reloads.");
  const [repeats, setRepeats] = useState<"1" | "3">("1");
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<CompareResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const stop = useRef<() => void>();
  const llmReady = status.data?.llm.status === "ok";

  useEffect(() => () => stop.current?.(), []);

  const watch = (cid: string) => {
    stop.current?.();
    stop.current = streamComparison(
      pid,
      cid,
      (stage, res) => {
        setSeen((s) => new Set([...s, stage]));
        if (res) {
          setResult(res);
          setRunning(false);
          emitScene({ type: "busy", value: false });
          invalidate(pid);
          if (res.status === "completed") {
            emitScene({ type: "wave", x: window.innerWidth / 2, y: 260, color: res.violation_delta > 0 ? "#43dcc8" : "#8d7cff" });
          } else if (res.error) setError(Object.assign(new Error(res.error.message), { code: res.error.code }));
        }
      },
      (e) => { setError(e); setRunning(false); },
    );
  };

  const run = async () => {
    setError(null);
    setResult(null);
    setSeen(new Set(["queued"]));
    setRunning(true);
    emitScene({ type: "busy", value: true });
    try {
      const { comparison_id } = await api.startCompare(pid, { task, repeats: Number(repeats) });
      watch(comparison_id);
    } catch (e) {
      setError(e);
      setRunning(false);
      emitScene({ type: "busy", value: false });
      toast.error(e);
    }
  };

  const loadPast = async (cid: string) => {
    setError(null);
    try {
      const r = await api.comparison(pid, cid);
      setResult(r);
      setTask(r.task);
      setSeen(new Set(STAGES.map((s) => s.key)));
      if (r.status === "running") { setRunning(true); watch(cid); }
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Compare mode</div>
          <h1>Same model. Same task. One variable: memory.</h1>
          <p>Both runs are real model calls at temperature 0 with identical prompts except one <code>&lt;project_memory&gt;</code> block. Memory Check then judges both outputs blind. Nothing is cached, edited or hard-coded.</p>
        </div>
      </div>

      <div className="card glow">
        <div className="row wrap" style={{ marginBottom: 10 }}>
          <span className="section-label" style={{ margin: 0 }}>Demo tasks</span>
          {(demo.data ?? []).map((d) => (
            <button key={d.id} className="btn xs" onClick={() => setTask(d.task)} title={d.expect}>{d.label}</button>
          ))}
        </div>
        <textarea className="textarea" value={task} onChange={(e) => setTask(e.target.value)} style={{ minHeight: 70, fontSize: 15 }} />
        <div className="row wrap" style={{ marginTop: 10 }}>
          <Segmented id="repeats" value={repeats} onChange={setRepeats} options={[{ value: "1", label: "Run once" }, { value: "3", label: "Run 3× (variance)" }]} />
          <span className="spacer" />
          {!llmReady && <span className="small" style={{ color: "var(--amber)" }}>Compare needs an LLM (GROQ_API_KEY).</span>}
          <Button variant="primary" size="lg" icon={running ? Loader2 : Play} disabled={running || task.trim().length < 5 || !llmReady} onClick={run}>
            {running ? "Running…" : result ? "Rerun" : "Run comparison"}
          </Button>
        </div>
      </div>

      {(running || result) && <Stepper seen={seen} running={running} />}
      {error ? <ErrorCard error={error} onRetry={run} title="Comparison failed" /> : null}
      {result && result.status === "completed" && <SummaryStrip r={result} />}
      {result && result.status !== "running" && <Panes r={result} />}

      {!running && !result && (
        <div className="card">
          <div className="card-head"><h3><History /> Previous comparisons</h3></div>
          {history.data?.length ? (
            <div className="list">
              {history.data.map((c) => (
                <div key={c.id} className="list-item clickable" onClick={() => void loadPast(c.id)}>
                  <GitCompareArrows size={16} className="muted" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="small strong clip">{c.task}</div>
                    <div className="tiny faint">{c.repeats}× · {c.status} · {timeAgo(c.created_at)}</div>
                  </div>
                  <span className="mono" style={{ color: "var(--red)" }}>{String((c.summary as Record<string, unknown>).mean_violations_baseline ?? c.violations_baseline)}</span>
                  <ArrowRight size={13} className="faint" />
                  <span className="mono" style={{ color: "var(--green)" }}>{String((c.summary as Record<string, unknown>).mean_violations_memory ?? c.violations_memory)}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={GitCompareArrows} title="No comparisons yet">Pick the hero task and run it. Approve the S-104 candidates in the Inbox first — that is the memory the right pane will use.</EmptyState>
          )}
        </div>
      )}
    </div>
  );
}

function Stepper({ seen, running }: { seen: Set<string>; running: boolean }) {
  const doneIdx = STAGES.reduce((acc, s, i) => (seen.has(s.key) ? i : acc), 0);
  return (
    <div className="stepper">
      {STAGES.map((s, i) => {
        const done = seen.has(s.key) || (!running && seen.size > 0);
        const active = running && !seen.has(s.key) && i === doneIdx + 1;
        return (
          <motion.span key={s.key} className={`step ${done ? "done" : ""} ${active ? "active" : ""}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            {done ? <CheckCircle2 /> : active ? <Loader2 className="spin" /> : <CircleDashed />}
            {s.label}
          </motion.span>
        );
      })}
    </div>
  );
}

function SummaryStrip({ r }: { r: CompareResult }) {
  const s = r.summary;
  return (
    <motion.div className="strip" initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", bounce: 0.25 }}>
      <div>
        <div className="tiny muted strong">VIOLATIONS</div>
        <div className="row" style={{ gap: 14 }}>
          <span className="big" style={{ color: "var(--red)" }}><AnimatedNumber value={r.violations_baseline} decimals={Number.isInteger(r.violations_baseline) ? 0 : 1} /></span>
          <ArrowRight size={26} className="muted" />
          <span className="big" style={{ color: "var(--green)" }}><AnimatedNumber value={r.violations_memory} decimals={Number.isInteger(r.violations_memory) ? 0 : 1} /></span>
        </div>
        {r.repeats > 1 && <div className="tiny faint">per run: {(s.violations_baseline_per_run ?? []).join(" · ")} → {(s.violations_memory_per_run ?? []).join(" · ")}</div>}
      </div>
      <Metric label="Records applied" value={r.applied_count} />
      <Metric label="Recalled" value={Number(s.records_recalled ?? 0)} />
      <Metric label="Memory tokens injected" value={r.injected_tokens} sub={s.all_records_tokens ? `vs ${s.all_records_tokens} to load every rule` : undefined} />
      <Metric label="Followed (cited)" value={Number(s.records_followed ?? 0)} />
      <div style={{ flex: "1 1 280px" }} className="small muted">
        <Sparkles size={13} style={{ verticalAlign: -2, color: "var(--teal)" }} /> {r.fairness.line}
        {typeof s.prompt_token_difference === "number" && <div className="tiny faint">Prompt token difference: +{s.prompt_token_difference}</div>}
      </div>
    </motion.div>
  );
}

function Metric({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div>
      <div className="tiny muted strong">{label.toUpperCase()}</div>
      <div style={{ fontSize: 24, fontWeight: 800 }}><AnimatedNumber value={value} /></div>
      {sub && <div className="tiny faint">{sub}</div>}
    </div>
  );
}

function Panes({ r }: { r: CompareResult }) {
  const [view, setView] = useState<"panes" | "diff">("panes");
  const [repeat, setRepeat] = useState(0);
  const base = r.baseline_runs[repeat] ?? r.baseline_run;
  const mem = r.memory_runs[repeat] ?? r.memory_run;
  const baseCheck = r.baseline_checks[repeat] ?? r.baseline_check;
  const memCheck = r.memory_checks[repeat] ?? r.memory_check;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="row wrap">
        <Segmented id="cmpview" value={view} onChange={setView} options={[{ value: "panes", label: "Side by side", icon: Columns2 }, { value: "diff", label: "Diff", icon: FileDiff }]} />
        {r.repeats > 1 && (
          <Segmented id="repeat" value={String(repeat)} onChange={(v) => setRepeat(Number(v))} options={r.baseline_runs.map((_, i) => ({ value: String(i), label: `Run ${i + 1}` }))} />
        )}
      </div>
      <AnimatePresence mode="wait">
        {view === "panes" ? (
          <motion.div key="panes" className="compare-grid" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <Pane title="Without memory" subtitle="Baseline · no recall call" run={base} check={baseCheck} tone="bad" />
            <Pane title="With ProjectPulse" subtitle="Hindsight recall + applicability filter" run={mem} check={memCheck} tone="ok" />
          </motion.div>
        ) : (
          <motion.div key="diff" className="card flush" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="code-head">baseline → memory-aware (all files)</div>
            <div className="diff" style={{ maxHeight: "70vh", overflow: "auto" }}>
              {diffLines(runText(base), runText(mem)).map((part, i) => (
                <span key={i} className={part.added ? "add" : part.removed ? "del" : ""}>{part.value}</span>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function runText(run?: TaskRun | null): string {
  if (!run) return "";
  return [run.output.summary, ...run.output.notes.map((n) => `- ${n}`), ...run.output.files.map((f) => `\n// ${f.path}\n${f.content}`)].join("\n");
}

function Pane({ title, subtitle, run, check, tone }: { title: string; subtitle: string; run?: TaskRun | null; check?: CheckResult | null; tone: "ok" | "bad" }) {
  const [showRecall, setShowRecall] = useState(false);
  const marks = (check?.violations ?? []).map((v) => ({ text: v.excerpt, tone: "bad" as const }));
  const count = check?.violations.filter((v) => v.severity !== "low").length ?? 0;
  return (
    <div className={`card pane ${tone === "ok" ? "memory" : ""}`}>
      <div className="pane-head">
        <div className="icon" style={{ background: tone === "ok" ? "linear-gradient(135deg,#6d5cf0,#3ab9c4)" : "#1d2340" }}>{tone === "ok" ? <Brain size={17} /> : <Circle size={17} />}</div>
        <div><div className="strong">{title}</div><div className="tiny faint">{subtitle}</div></div>
        <span className="spacer" />
        {run && <span className="tiny faint mono">{run.model ?? "—"} · {ms(run.latency_ms)}{run.usage.prompt_tokens ? ` · ${run.usage.prompt_tokens} prompt tok` : ""}</span>}
      </div>
      {run?.status === "blocked" && <div className="callout bad small">Memory-aware run blocked: {run.error?.message}. The baseline still ran.</div>}
      {run?.status === "error" && <ErrorCard error={Object.assign(new Error(run.error?.message ?? "Generation failed"), { code: run.error?.code })} />}
      {check && (
        <div className={`verdict ${check.verdict === "violations" ? "bad" : check.verdict === "compliant" ? "ok" : "na"}`}>
          {check.verdict === "violations" ? <ShieldAlert color="var(--red)" /> : <ShieldCheck color="var(--green)" />}
          <span className="num" style={{ color: check.verdict === "violations" ? "var(--red)" : "var(--green)" }}>{count}</span>
          <div style={{ flex: 1 }}>
            <div className="strong">{check.verdict === "violations" ? `violation${count === 1 ? "" : "s"} of decisions this team made` : check.verdict === "compliant" ? "Compliant with project memory" : "Check unavailable"}</div>
            <div className="tiny faint">Memory Check · {check.judge_mode} judge · {check.recalled_records.length} decisions considered</div>
          </div>
        </div>
      )}
      {run?.brief && run.brief.applied.length > 0 && (
        <div className="row wrap" style={{ gap: 6 }}>
          <span className="tiny muted">Applied:</span>
          {run.brief.applied.map((a) => <ProvenancePill key={a.record.id} record={a.record} />)}
          <button className="btn xs ghost" onClick={() => setShowRecall(!showRecall)}><Radar /> Recall panel</button>
        </div>
      )}
      {showRecall && run?.brief && <div className="card tight"><RecallPanel brief={run.brief} compact /></div>}
      {check?.violations.map((v, i) => (
        <motion.div key={i} className="recall-item" style={{ borderColor: "rgba(255,92,120,.35)" }} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }}>
          <div className="row"><ProvenancePill record={{ id: v.record_id, pill: v.record_pill, type: "security_constraint", area: null, status: "active" }} showArea={false} /><span className="small strong clip">{v.record_title}</span><span className="spacer" /><StatusPill tone={v.severity === "high" ? "bad" : "warn"} label={v.severity} /></div>
          <code className="small" style={{ color: "#ffb3c1" }}>“{v.excerpt}”</code>
          <div className="small muted">{v.explanation}</div>
          {v.suggested_fix && <div className="small" style={{ color: "#b4f7da" }}>Fix: {v.suggested_fix}</div>}
        </motion.div>
      ))}
      {run && run.status === "ok" && (
        <>
          <div className="small" style={{ lineHeight: 1.6 }}>{run.output.summary}</div>
          {run.output.files.map((f) => <CodeBlock key={f.path} code={f.content} path={f.path} language={f.language} marks={marks} />)}
          {run.output.notes.length > 0 && <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>{run.output.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </>
      )}
    </div>
  );
}
