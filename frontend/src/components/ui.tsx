import { AnimatePresence, animate, motion, useInView } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Info,
  Loader2,
  RotateCw,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, type RecordRef } from "../lib/api";
import { typeMeta } from "../lib/meta";
import { useRecordDrawer } from "./drawerContext";

// ------------------------------------------------------------------ primitives
export function Button({
  children,
  variant,
  size,
  icon: Icon,
  loading,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "success";
  size?: "sm" | "xs" | "lg";
  icon?: LucideIcon;
  loading?: boolean;
}) {
  return (
    <button className={`btn ${variant ?? ""} ${size ?? ""} ${className}`} disabled={loading || rest.disabled} {...rest}>
      {loading ? <Loader2 className="spin" /> : Icon ? <Icon /> : null}
      {children}
    </button>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <span className="kbd">{children}</span>;
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)} role="switch" aria-checked={on}>
      <span className="toggle-track"><span className="toggle-thumb" /></span>
      {label}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  id,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; icon?: LucideIcon }[];
  id: string;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? "active" : ""} onClick={() => onChange(o.value)} role="tab">
          {value === o.value && <motion.span layoutId={`seg-${id}`} className="seg-bg" transition={{ type: "spring", bounce: 0.2, duration: 0.45 }} />}
          {o.icon && <o.icon />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ memory pills
export function TypeBadge({ type, compact }: { type: string; compact?: boolean }) {
  const meta = typeMeta(type);
  const Icon = meta.icon;
  return (
    <span className="type-badge" style={{ color: meta.color, background: `${meta.color}1a`, border: `1px solid ${meta.color}40` }}>
      <Icon />
      {compact ? meta.short : meta.label}
    </span>
  );
}

/** MEM-7F3A · security — opens the Record drawer everywhere it appears. */
export function ProvenancePill({ record, showArea = true }: { record: Pick<RecordRef, "id" | "pill" | "type" | "area" | "status">; showArea?: boolean }) {
  const open = useRecordDrawer();
  const meta = typeMeta(record.type);
  const Icon = meta.icon;
  return (
    <button
      type="button"
      className={`prov ${record.status && record.status !== "active" ? "retired" : ""}`}
      style={{ borderColor: `${meta.color}66`, boxShadow: `inset 3px 0 0 ${meta.color}` }}
      onClick={(e) => {
        e.stopPropagation();
        open(record.id);
      }}
      title={`${record.pill} — open record`}
    >
      <Icon style={{ color: meta.color }} />
      {record.pill}
      {showArea && record.area && (
        <>
          <span className="sep">·</span>
          <span className="area">{record.area}</span>
        </>
      )}
    </button>
  );
}

export function ConfidenceBand({ band }: { band: "high" | "medium" | "low" }) {
  return (
    <span className="row" style={{ gap: 6 }} title={`Confidence: ${band}`}>
      <span className={`band ${band}`}><i /><i /><i /></span>
      <span className="tiny muted">{band}</span>
    </span>
  );
}

export function StatusPill({ tone, label, live, icon: Icon }: { tone: "ok" | "warn" | "bad" | "info" | "violet" | "none"; label: ReactNode; live?: boolean; icon?: LucideIcon }) {
  return (
    <span className={`pill ${tone} ${live ? "live" : ""}`}>
      {Icon ? <Icon /> : <span className="dot" />}
      {label}
    </span>
  );
}

export function RetainState({ state }: { state?: string | null }) {
  if (!state || state === "retained") return <StatusPill tone="ok" label="In Hindsight" />;
  if (state === "pending") return <StatusPill tone="warn" label="Waiting to sync" live />;
  if (state === "retag_pending") return <StatusPill tone="warn" label="Syncing status" live />;
  return <StatusPill tone="bad" label="Retain failed" />;
}

// ------------------------------------------------------------------ states
export function Skeleton({ h = 16, w = "100%", r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: r }} />;
}

export function SkeletonList({ rows = 4, h = 64 }: { rows?: number; h?: number }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} h={h} r={12} />)}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <motion.div className="empty" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <div className="empty-icon floaty"><Icon /></div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </motion.div>
  );
}

export function ErrorCard({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const err = error as ApiError;
  const [raw, setRaw] = useState(false);
  const rawText = (err?.details as { raw?: string } | undefined)?.raw;
  return (
    <div className="error-card" role="alert">
      <XCircle size={18} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="strong">{title ?? "Something went wrong"}</div>
        <div className="small" style={{ color: "#ffd0da", marginTop: 2 }}>{err?.message ?? String(error)}</div>
        <div className="row" style={{ marginTop: 6, gap: 10 }}>
          {err?.code && <span className="code">{err.code}</span>}
          {err?.requestId && <span className="code">request {err.requestId}</span>}
          {rawText && <button className="btn xs ghost" onClick={() => setRaw(!raw)}>{raw ? "Hide" : "Show"} raw output</button>}
        </div>
        {raw && rawText && <pre className="code-block" style={{ padding: 10, marginTop: 8, whiteSpace: "pre-wrap", fontSize: 11 }}>{rawText}</pre>}
      </div>
      {onRetry && <Button size="sm" icon={RotateCw} onClick={onRetry}>Retry</Button>}
    </div>
  );
}

// ------------------------------------------------------------------ numbers
export function AnimatedNumber({ value, decimals = 0, suffix = "" }: { value: number | null | undefined; decimals?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (!inView || value === null || value === undefined) return;
    const controls = animate(from.current, value, {
      duration: 1.1,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setShown(v),
      onComplete: () => { from.current = value; },
    });
    return () => { controls.stop(); from.current = value; };
  }, [value, inView]);
  return <span ref={ref}>{value === null || value === undefined ? "—" : shown.toFixed(decimals) + suffix}</span>;
}

export function Stat({ label, value, sub, icon: Icon, accent, decimals, suffix }: { label: string; value: number | null | undefined; sub?: ReactNode; icon?: LucideIcon; accent?: string; decimals?: number; suffix?: string }) {
  return (
    <motion.div className="card stat hover" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
      <div className="label">{Icon && <Icon style={{ color: accent ?? "var(--violet)" }} />}{label}</div>
      <div className="value" style={accent ? { color: accent } : undefined}><AnimatedNumber value={value} decimals={decimals} suffix={suffix} /></div>
      {sub && <div className="sub">{sub}</div>}
      {Icon && <Icon className="spark" style={{ color: accent ?? "var(--violet)" }} />}
    </motion.div>
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; kind: "success" | "error" | "info"; text: ReactNode };
const ToastCtx = createContext<(kind: Toast["kind"], text: ReactNode) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: ReactNode) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        <AnimatePresence>
          {toasts.map((t) => {
            const Icon = t.kind === "success" ? CheckCircle2 : t.kind === "error" ? AlertTriangle : Info;
            return (
              <motion.div key={t.id} className={`toast ${t.kind}`} initial={{ opacity: 0, x: 40, scale: 0.96 }} animate={{ opacity: 1, x: 0, scale: 1 }} exit={{ opacity: 0, x: 40 }}>
                <Icon />
                <div style={{ flex: 1 }}>{t.text}</div>
                <button className="btn xs ghost" onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}><X /></button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return useMemo(
    () => ({
      success: (t: ReactNode) => push("success", t),
      error: (e: unknown) => push("error", e instanceof Error ? e.message : String(e)),
      info: (t: ReactNode) => push("info", t),
    }),
    [push],
  );
}

// ------------------------------------------------------------------ modal
export function Modal({ open, onClose, children, width }: { open: boolean; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <div className="modal-wrap" onClick={onClose}>
            <motion.div
              className="modal"
              style={width ? { width: `min(${width}px, 100%)` } : undefined}
              initial={{ opacity: 0, y: 24, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 16, scale: 0.98 }}
              transition={{ type: "spring", bounce: 0.18, duration: 0.45 }}
              onClick={(e) => e.stopPropagation()}
            >
              {children}
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}

// ------------------------------------------------------------------ code
const TOKEN =
  /(\/\/[^\n]*|^\s*#[^\n]*)|("[^"\n]*"|'[^'\n]*'|`[^`]*`)|\b(import|from|export|default|const|let|var|function|async|await|return|if|else|for|while|new|class|extends|try|catch|throw|type|interface|def|self|None|True|False|null|undefined|true|false)\b|\b(\d+)\b/gm;

function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Single-pass tokenizer: never re-scans its own HTML output. */
function tokenize(code: string): string {
  let out = "";
  let last = 0;
  for (const m of code.matchAll(TOKEN)) {
    const idx = m.index ?? 0;
    out += esc(code.slice(last, idx));
    const cls = m[1] ? "tok-c" : m[2] ? "tok-s" : m[3] ? "tok-k" : "tok-n";
    out += `<span class="${cls}">${esc(m[0])}</span>`;
    last = idx + m[0].length;
  }
  return out + esc(code.slice(last));
}

function highlight(code: string, marks: { text: string; tone: "bad" | "ok" }[] = []): string {
  // Mark ranges first (e.g. violating excerpts), tokenize everything between them.
  const ranges: { start: number; end: number; tone: string }[] = [];
  for (const mark of marks) {
    if (mark.text.length < 3) continue;
    let from = 0;
    for (;;) {
      const i = code.indexOf(mark.text, from);
      if (i < 0) break;
      if (!ranges.some((r) => i < r.end && i + mark.text.length > r.start)) {
        ranges.push({ start: i, end: i + mark.text.length, tone: mark.tone });
      }
      from = i + mark.text.length;
    }
  }
  ranges.sort((x, y) => x.start - y.start);
  let out = "";
  let pos = 0;
  for (const r of ranges) {
    out += tokenize(code.slice(pos, r.start));
    out += `<span class="hl-${r.tone}">${esc(code.slice(r.start, r.end))}</span>`;
    pos = r.end;
  }
  return out + tokenize(code.slice(pos));
}

export function CodeBlock({ code, path, language, marks }: { code: string; path?: string; language?: string; marks?: { text: string; tone: "bad" | "ok" }[] }) {
  const toast = useToast();
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="dots"><i /><i /><i /></span>
        <span className="clip" style={{ flex: 1 }}>{path ?? language ?? "snippet"}</span>
        <button className="btn xs ghost" onClick={() => void navigator.clipboard?.writeText(code).then(() => toast.success("Copied"))}><Copy /></button>
      </div>
      <pre dangerouslySetInnerHTML={{ __html: highlight(code, marks) }} />
    </div>
  );
}

// ------------------------------------------------------------------ markdown
function inline(text: string): string {
  // Code spans are rendered verbatim; emphasis rules only apply outside them.
  return text
    .split(/(`[^`]+`)/g)
    .map((part) => {
      if (part.startsWith("`") && part.endsWith("`") && part.length > 1) return `<code>${esc(part.slice(1, -1))}</code>`;
      return esc(part)
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
        .replace(/(^|\s)_([^_\n]+)_(?=\s|[.,;:!?)]|$)/g, "$1<em>$2</em>");
    })
    .join("");
}

export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const lines = (text || "").split("\n");
    const out: string[] = [];
    let list = false;
    let table: string[][] | null = null;
    const flushTable = () => {
      if (!table) return;
      const [head, ...rows] = table.filter((r) => !r.every((c) => /^:?-{2,}:?$/.test(c.trim())));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c.trim())}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c.trim())}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      table = null;
    };
    for (const raw of lines) {
      const line = raw.trimEnd();
      if (/^\s*\|.*\|\s*$/.test(line)) {
        if (list) { out.push("</ul>"); list = false; }
        table = table ?? [];
        table.push(line.trim().slice(1, -1).split("|"));
        continue;
      }
      flushTable();
      const h = line.match(/^(#{1,4})\s+(.*)/);
      const li = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);
      if (li) {
        if (!list) { out.push("<ul>"); list = true; }
        out.push(`<li>${inline(li[1])}</li>`);
        continue;
      }
      if (list) { out.push("</ul>"); list = false; }
      if (h) out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
      else if (/^(-{3,}|\*{3,})$/.test(line.trim())) out.push("<hr/>");
      else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    }
    flushTable();
    if (list) out.push("</ul>");
    return out.join("");
  }, [text]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}

// ------------------------------------------------------------------ misc
export function Section({ label, children, right }: { label: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <div>
      <div className="section-label">{label}{right && <><span className="spacer" />{right}</>}</div>
      {children}
    </div>
  );
}

export function Meter({ value }: { value: number }) {
  return (
    <div className="meter">
      <motion.i initial={{ width: 0 }} animate={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
    </div>
  );
}

export function Spotlight({ children, className = "", style, onClick }: { children: ReactNode; className?: string; style?: React.CSSProperties; onClick?: () => void }) {
  return (
    <div
      className={`card spotlight hover ${className}`}
      style={style}
      onClick={onClick}
      onMouseMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        e.currentTarget.style.setProperty("--mx", `${e.clientX - rect.left}px`);
        e.currentTarget.style.setProperty("--my", `${e.clientY - rect.top}px`);
      }}
    >
      {children}
    </div>
  );
}
