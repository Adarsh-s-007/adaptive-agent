import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Filter, Radar, Sparkles, Timer, Zap } from "lucide-react";
import { useState } from "react";
import type { Brief } from "../lib/api";
import { ms } from "../lib/meta";
import { Meter, ProvenancePill, StatusPill } from "./ui";

const STATUS: Record<Brief["status"], { tone: "ok" | "warn" | "bad" | "info" | "violet"; label: string }> = {
  ok: { tone: "ok", label: "Memory applied" },
  none_apply: { tone: "info", label: "Recalled, none apply" },
  empty: { tone: "info", label: "No memory applies" },
  unfiltered: { tone: "warn", label: "Unfiltered (top 3)" },
  memory_unavailable: { tone: "bad", label: "Memory unavailable" },
};

/** Shows what was recalled, what was applied (with reasons) and what was filtered out (with reasons). */
export function RecallPanel({ brief, compact }: { brief: Brief | null | undefined; compact?: boolean }) {
  const [showFiltered, setShowFiltered] = useState(!compact);
  if (!brief) {
    return (
      <div className="empty" style={{ padding: 24 }}>
        <div className="empty-icon"><Radar /></div>
        <h3>Recall panel</h3>
        <p>Send a task with “Use project memory” on. You will see what Hindsight recalled, what applied and why, and what was filtered out.</p>
      </div>
    );
  }
  const st = STATUS[brief.status] ?? STATUS.empty;
  const saving = brief.all_records_tokens > 0 ? 1 - brief.injected_tokens / brief.all_records_tokens : 0;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row wrap" style={{ gap: 8 }}>
        <StatusPill tone={st.tone} label={st.label} />
        {brief.filter_mode === "heuristic" && <StatusPill tone="warn" label="Heuristic filter (no LLM)" icon={Zap} />}
      </div>
      {brief.message && <div className="small muted">{brief.message}</div>}

      <div className="grid-3" style={{ gap: 8 }}>
        <Metric icon={Radar} label="Recalled" value={String(brief.recalled.length)} />
        <Metric icon={Sparkles} label="Applied" value={String(brief.applied.length)} accent="var(--green)" />
        <Metric icon={Filter} label="Filtered" value={String(brief.filtered.length)} />
        <Metric icon={Timer} label="Recall" value={ms(brief.recall_ms)} sub={brief.recall_attempts > 1 ? `${brief.recall_attempts} attempts` : undefined} />
        <Metric icon={Timer} label="Filter" value={ms(brief.filter_ms)} />
        <Metric icon={Zap} label="Injected" value={`${brief.injected_tokens} tok`} sub={brief.all_records_tokens ? `of ${brief.all_records_tokens} for all` : undefined} />
      </div>
      {brief.all_records_tokens > 0 && (
        <div>
          <div className="row tiny muted" style={{ marginBottom: 5 }}>
            <span>Injected vs “load every rule”</span><span className="spacer" /><span>{Math.round(saving * 100)}% smaller</span>
          </div>
          <Meter value={brief.injected_tokens / brief.all_records_tokens} />
        </div>
      )}

      <div className="recall-group">
        <div className="section-label">Applied to the agent</div>
        <AnimatePresence>
          {brief.applied.map((a, i) => (
            <motion.div key={a.record.id} className="recall-item applied" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}>
              <div className="row"><ProvenancePill record={a.record} /><span className="spacer" /><span className="rank">#{a.recall_rank ?? a.rank} recall</span></div>
              <div className="small strong">{a.record.title}</div>
              <div className="reason">↳ {a.reason}</div>
              {a.record.tentative && <span className="tiny" style={{ color: "var(--amber)" }}>tentative — agent-proposed</span>}
            </motion.div>
          ))}
        </AnimatePresence>
        {!brief.applied.length && <div className="small faint">Nothing injected — the agent runs exactly like the baseline.</div>}
      </div>

      {brief.filtered.length > 0 && (
        <div className="recall-group">
          <button className="btn xs ghost" style={{ justifySelf: "start" }} onClick={() => setShowFiltered(!showFiltered)}>
            <ChevronDown style={{ transform: showFiltered ? "rotate(180deg)" : undefined, transition: "transform .2s" }} /> Filtered ({brief.filtered.length})
          </button>
          {showFiltered && brief.filtered.map((f) => (
            <motion.div key={f.record.id} className="recall-item filtered" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="row"><ProvenancePill record={f.record} /><span className="spacer" /><span className="rank">#{f.recall_rank ?? "—"} recall</span></div>
              <div className="reason">✕ {f.reason}</div>
            </motion.div>
          ))}
        </div>
      )}

      {brief.observations.length > 0 && !compact && (
        <div className="recall-group">
          <div className="section-label">Hindsight observations (consolidated beliefs)</div>
          {brief.observations.slice(0, 3).map((o, i) => <div key={i} className="small muted" style={{ borderLeft: "2px solid var(--violet)", paddingLeft: 10 }}>{o.text}</div>)}
        </div>
      )}
      <div className="tiny faint mono clip" title={brief.query}>query: {brief.query}</div>
    </div>
  );
}

function Metric({ icon: Icon, label, value, sub, accent }: { icon: typeof Radar; label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="card tight" style={{ padding: "9px 10px", background: "rgba(8,10,22,.6)" }}>
      <div className="tiny muted row" style={{ gap: 5 }}><Icon size={12} />{label}</div>
      <div className="strong" style={{ fontSize: 15, marginTop: 2, color: accent, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div className="tiny faint">{sub}</div>}
    </div>
  );
}
