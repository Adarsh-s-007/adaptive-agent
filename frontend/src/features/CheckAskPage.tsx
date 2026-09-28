import { AnimatePresence, motion } from "framer-motion";
import { Brain, CornerDownLeft, MessageCircleQuestion, ShieldAlert, ShieldCheck, ShieldQuestion, Sparkles, Zap } from "lucide-react";
import { useState } from "react";
import { Button, CodeBlock, EmptyState, ErrorCard, Markdown, ProvenancePill, Segmented, StatusPill, useToast } from "../components/ui";
import { api, type AskAnswer, type CheckResult } from "../lib/api";
import { useMutation, usePid } from "../lib/hooks";
import { ms } from "../lib/meta";

const SAMPLE = `// app/api/auth/login/route.ts
import { PrismaClient } from "@prisma/client";

export async function POST(req: Request) {
  const prisma = new PrismaClient();
  const { email, password } = await req.json();
  console.log("login attempt", email);
  const user = await prisma.user.findUnique({ where: { email } });
  const token = sign(user.id);
  return Response.json({ token });
}

// client
localStorage.setItem('token', token);`;

const QUESTIONS = ["Why don't we keep carts in Redis?", "How should the database client be configured on Vercel?", "What changed in auth this month?", "How do we store money?"];

export default function CheckAskPage() {
  const [tab, setTab] = useState<"check" | "ask">("check");
  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Check & Ask</div>
          <h1>Make memory enforceable</h1>
          <p>Check verifies any code, plan or diff against the decisions it might violate — with the offending excerpt and a fix. Ask answers from the team's own history with citations validated by Hindsight reflect.</p>
        </div>
        <Segmented id="ca" value={tab} onChange={setTab} options={[{ value: "check", label: "Memory Check", icon: ShieldCheck }, { value: "ask", label: "Ask the project", icon: MessageCircleQuestion }]} />
      </div>
      {tab === "check" ? <CheckTab /> : <AskTab />}
    </div>
  );
}

function CheckTab() {
  const pid = usePid();
  const toast = useToast();
  const [content, setContent] = useState(SAMPLE);
  const m = useMutation({ mutationFn: () => api.check(pid, content), onError: (e) => toast.error(e) });
  const r = m.data;
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <div className="card">
        <div className="card-head"><h3><CornerDownLeft /> Paste code, a plan or a diff</h3><span className="tiny faint">{content.length.toLocaleString()} / 60,000</span></div>
        <textarea className="textarea code" style={{ minHeight: 380 }} value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="row" style={{ marginTop: 10 }}>
          <Button size="sm" variant="ghost" onClick={() => setContent(SAMPLE)}>Load sample</Button>
          <span className="spacer" />
          <Button variant="primary" icon={ShieldCheck} loading={m.isPending} disabled={content.trim().length < 5} onClick={() => m.mutate()}>Run Memory Check</Button>
        </div>
      </div>
      <div className="stack">
        {m.isPending && <div className="card" style={{ position: "relative", overflow: "hidden", minHeight: 160 }}><div className="scanline" /><div className="strong">Checking…</div><div className="small muted">recalling decisions this output might violate → judging → dropping any finding whose excerpt is not verbatim</div></div>}
        {m.error && <ErrorCard error={m.error} onRetry={() => m.mutate()} />}
        {!r && !m.isPending && <EmptyState icon={ShieldQuestion} title="No check yet">Run Memory Check on the sample: a new PrismaClient per request, PII in logs, a token in localStorage and an ad-hoc response shape.</EmptyState>}
        {r && <CheckResultView r={r} content={content} />}
      </div>
    </div>
  );
}

export function CheckResultView({ r, content }: { r: CheckResult; content?: string }) {
  const bad = r.verdict === "violations";
  return (
    <motion.div className="stack" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <div className={`verdict ${bad ? "bad" : r.verdict === "compliant" ? "ok" : "na"}`}>
        {bad ? <ShieldAlert color="var(--red)" size={26} /> : <ShieldCheck color="var(--green)" size={26} />}
        <div style={{ flex: 1 }}>
          <div className="strong" style={{ fontSize: 16 }}>{bad ? `${r.violations.length} violation${r.violations.length === 1 ? "" : "s"}` : r.verdict === "compliant" ? "Compliant" : "Check unavailable"}</div>
          <div className="tiny faint">{r.judge_mode} judge{r.judge_model ? ` · ${r.judge_model}` : ""} · {r.recalled_records.length} decisions considered · {ms(r.latency_ms)}{r.dropped_findings ? ` · ${r.dropped_findings} unverifiable findings dropped` : ""}</div>
        </div>
        {r.judge_mode === "heuristic" && <StatusPill tone="warn" icon={Zap} label="heuristic" />}
      </div>
      {r.message && <div className="callout warn small">{r.message}</div>}
      <AnimatePresence>
        {r.violations.map((v, i) => (
          <motion.div key={i} className="card tight" style={{ borderColor: "rgba(255,92,120,.35)" }} initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.07 }}>
            <div className="row wrap"><ProvenancePill record={{ id: v.record_id, pill: v.record_pill, type: "decision", area: null, status: "active" }} showArea={false} /><span className="strong small">{v.record_title}</span><span className="spacer" /><StatusPill tone={v.severity === "high" ? "bad" : "warn"} label={v.severity} /></div>
            <div className="small muted" style={{ margin: "8px 0" }}>{v.rule_statement}</div>
            <code className="small" style={{ color: "#ffb3c1", display: "block", background: "rgba(255,92,120,.08)", padding: "6px 9px", borderRadius: 7 }}>{v.excerpt}</code>
            {v.explanation && <div className="small" style={{ marginTop: 8 }}>{v.explanation}</div>}
            {v.suggested_fix && <div className="small" style={{ marginTop: 6, color: "#b4f7da" }}>↳ {v.suggested_fix}</div>}
            {v.pattern_evidence.length > 0 && <div className="tiny faint mono" style={{ marginTop: 6 }}>pattern evidence: {v.pattern_evidence.join(", ")}</div>}
          </motion.div>
        ))}
      </AnimatePresence>
      {r.warnings.length > 0 && (
        <div className="card tight">
          <div className="section-label">Warnings (tentative records or uncertain matches)</div>
          {r.warnings.map((w, i) => <div key={i} className="small" style={{ marginBottom: 6 }}><ProvenancePill record={{ id: w.record_id, pill: w.record_pill, type: "decision", area: null, status: "active" }} showArea={false} /> <span className="muted">{w.explanation}</span></div>)}
        </div>
      )}
      {r.conflicts.length > 0 && <div className="callout bad small"><b>Memory conflict — needs a human decision:</b> {r.conflicts.map((c) => `${c.record_pills.join(" vs ")}: ${c.explanation}`).join("; ")}</div>}
      {content && r.violations.length > 0 && <CodeBlock code={content} path="checked content" marks={r.violations.map((v) => ({ text: v.excerpt, tone: "bad" as const }))} />}
      {r.recalled_records.length > 0 && (
        <div className="row wrap" style={{ gap: 6 }}><span className="tiny muted">Considered:</span>{r.recalled_records.map((rec) => <ProvenancePill key={rec.id} record={rec} />)}</div>
      )}
    </motion.div>
  );
}

function AskTab() {
  const pid = usePid();
  const [question, setQuestion] = useState(QUESTIONS[0]);
  const [history, setHistory] = useState<AskAnswer[]>([]);
  const m = useMutation({ mutationFn: (q: string) => api.ask(pid, q), onSuccess: (a) => setHistory((h) => [a, ...h]) });
  return (
    <div className="stack">
      <div className="card glow">
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (question.trim().length > 2) m.mutate(question.trim()); }}>
          <Brain className="muted" />
          <input className="input" style={{ fontSize: 15 }} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask why the team decided something…" />
          <Button variant="primary" icon={Sparkles} loading={m.isPending}>Ask</Button>
        </form>
        <div className="row wrap" style={{ marginTop: 10, gap: 6 }}>
          {QUESTIONS.map((q) => <button key={q} className="btn xs" onClick={() => { setQuestion(q); m.mutate(q); }}>{q}</button>)}
        </div>
      </div>
      {m.isPending && <div className="card" style={{ position: "relative", overflow: "hidden" }}><div className="scanline" /><div className="strong">Reflecting over project memory…</div><div className="small muted">Hindsight searches facts, observations and the Rulebook, then answers with guardrail directives applied.</div></div>}
      {m.error && <ErrorCard error={m.error} onRetry={() => m.mutate(question)} title="Ask is temporarily unavailable" />}
      {!history.length && !m.isPending && <EmptyState icon={MessageCircleQuestion} title="Ask the project">Answers come from Hindsight reflect over this project's bank only, citing the records they are based on.</EmptyState>}
      {history.map((a, i) => (
        <motion.div key={i} className="card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="row"><MessageCircleQuestion size={16} className="muted" /><span className="strong">{a.question}</span><span className="spacer" /><span className="tiny faint">{ms(a.latency_ms)}</span></div>
          <div style={{ marginTop: 10 }}><Markdown text={a.answer} /></div>
          {a.based_on.length > 0 && <div className="row wrap" style={{ marginTop: 10, gap: 6 }}><span className="tiny muted">Based on:</span>{a.based_on.map((r) => <ProvenancePill key={r.id} record={r} />)}</div>}
          {a.guardrails.length > 0 && <div className="tiny faint" style={{ marginTop: 8 }}>Guardrails applied: {a.guardrails.map((g) => g.name).join(" · ")}</div>}
        </motion.div>
      ))}
    </div>
  );
}
