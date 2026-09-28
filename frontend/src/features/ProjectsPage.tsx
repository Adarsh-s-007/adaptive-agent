import { motion } from "framer-motion";
import { ArrowRight, Boxes, Brain, Database, Loader2, Plus, Rocket, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, EmptyState, ErrorCard, Modal, Skeleton, Spotlight, StatusPill, useToast } from "../components/ui";
import { api, type Project } from "../lib/api";
import { keys, useMutation, useProjects, useQueryClient } from "../lib/hooks";
import { timeAgo, typeMeta } from "../lib/meta";

const LOOP = ["Capture", "Extract", "Review", "Retain", "Brief", "Generate", "Check"];

export default function ProjectsPage() {
  const projects = useProjects();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const seed = useMutation({
    mutationFn: (which: "apexcart" | "ledgerlite") => api.seed(which),
    onSuccess: (res, which) => {
      toast.success(`${which === "apexcart" ? "ApexCart" : "LedgerLite"} ready — ${res.records_created} records retained into its own Hindsight bank${res.transcripts_imported ? `, ${res.transcripts_imported} sessions waiting for extraction` : ""}.`);
      void qc.invalidateQueries({ queryKey: keys.projects });
      navigate(`/p/${res.project_id}`);
    },
    onError: (e) => toast.error(e),
  });

  return (
    <div className="stack" style={{ gap: 26 }}>
      <motion.section className="hero" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
        <div className="scanline" />
        <div className="eyebrow">Governed memory for AI coding agents · powered by Hindsight</div>
        <h1>
          One correction, captured once,<br />
          <span className="gradient-text">applied and checked in every later session.</span>
        </h1>
        <p>
          ProjectPulse turns what one agent session learned into reviewed project memory, briefs the next session with only
          the decisions that apply, and checks that session's output against them — with a measured before/after.
        </p>
        <div className="row wrap" style={{ gap: 12 }}>
          <Button variant="primary" size="lg" icon={Rocket} loading={seed.isPending && seed.variables === "apexcart"} onClick={() => seed.mutate("apexcart")}>
            Launch the ApexCart demo
          </Button>
          <Button size="lg" icon={ShieldCheck} loading={seed.isPending && seed.variables === "ledgerlite"} onClick={() => seed.mutate("ledgerlite")}>
            Add LedgerLite (isolation)
          </Button>
          <Button size="lg" variant="ghost" icon={Plus} onClick={() => setCreating(true)}>New project</Button>
        </div>
        <div className="loop">
          {LOOP.map((s, i) => (
            <motion.span key={s} className={`loop-step ${s === "Check" || s === "Review" ? "hot" : ""}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 + i * 0.07 }}>
              <b>{i + 1}</b> {s}
            </motion.span>
          ))}
          <motion.span className="loop-step" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.9 }}>
            <Brain size={13} /> Reflect → Rulebook · Ask
          </motion.span>
        </div>
      </motion.section>

      <div className="page-head">
        <div>
          <div className="eyebrow">Projects</div>
          <h1>Memory spaces</h1>
          <p>Every project provisions its own Hindsight bank — a hard isolation boundary. Nothing crosses between projects.</p>
        </div>
      </div>

      {projects.isLoading && <div className="grid-3">{[0, 1, 2].map((i) => <Skeleton key={i} h={200} r={14} />)}</div>}
      {projects.error && <ErrorCard error={projects.error} onRetry={() => projects.refetch()} />}
      {projects.data && projects.data.length === 0 && (
        <EmptyState icon={Database} title="No projects yet" action={<Button variant="primary" icon={Rocket} onClick={() => seed.mutate("apexcart")} loading={seed.isPending}>Launch the ApexCart demo</Button>}>
          Launch the demo to get a realistic storefront history (13 decisions from April–August, plus two sessions to extract live), or create an empty project.
        </EmptyState>
      )}
      <div className="grid-3">
        {(projects.data ?? []).map((p, i) => (
          <motion.div key={p.id} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
            <ProjectCard project={p} onOpen={() => navigate(`/p/${p.id}`)} />
          </motion.div>
        ))}
      </div>
      <CreateProjectModal open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

function ProjectCard({ project: p, onOpen }: { project: Project; onOpen: () => void }) {
  const types = Object.entries(p.stats.active_by_type ?? {});
  return (
    <Spotlight className="project-card" onClick={onOpen}>
      <div className="row">
        <span className="brand-mark" style={{ width: 36, height: 36, fontSize: 16, borderRadius: 11 }}>{p.name[0]}</span>
        <div style={{ minWidth: 0 }}>
          <div className="strong" style={{ fontSize: 16 }}>{p.name}</div>
          <div className="tiny faint clip">{p.tech_stack || p.description || "—"}</div>
        </div>
        <span className="spacer" />
        {p.bank_status === "ready" ? <StatusPill tone="ok" label="ready" live /> : p.bank_status === "provisioning" ? <StatusPill tone="warn" label={<><Loader2 size={11} className="spin" /> provisioning</>} /> : <StatusPill tone="bad" label="bank error" />}
      </div>
      <div className="muted small" style={{ minHeight: 40 }}>{p.description || "No description."}</div>
      <div className="row" style={{ gap: 18 }}>
        <div><div style={{ fontSize: 22, fontWeight: 800 }}>{p.stats.active_records}</div><div className="tiny faint">active rules</div></div>
        <div><div style={{ fontSize: 22, fontWeight: 800, color: p.stats.pending_candidates ? "var(--pink)" : undefined }}>{p.stats.pending_candidates}</div><div className="tiny faint">to review</div></div>
        <div><div style={{ fontSize: 22, fontWeight: 800 }}>{p.stats.superseded_records}</div><div className="tiny faint">superseded</div></div>
        <span className="spacer" />
        <ArrowRight className="muted" />
      </div>
      {types.length > 0 && (
        <div className="row" style={{ gap: 2, height: 6, borderRadius: 6, overflow: "hidden" }}>
          {types.map(([t, n]) => <span key={t} title={`${typeMeta(t).label}: ${n}`} style={{ flex: n, height: "100%", background: typeMeta(t).color }} />)}
        </div>
      )}
      <div className="row tiny faint"><span className="bank-id">{p.bank_id}</span><span className="spacer" />{timeAgo(p.stats.last_activity_at ?? p.created_at)}</div>
    </Spotlight>
  );
}

function CreateProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form, setForm] = useState({ name: "", description: "", tech_stack: "", areas: "auth, api, database, frontend" });
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.createProject({ ...form, areas: form.areas.split(",").map((a) => a.trim()).filter(Boolean) }),
    onSuccess: (p) => {
      toast.success(p.bank_status === "ready" ? `Provisioned ${p.bank_id} with missions, 3 directives and the Rulebook model.` : `Project created; bank is ${p.bank_status}.`);
      void qc.invalidateQueries({ queryKey: keys.projects });
      onClose();
      navigate(`/p/${p.id}`);
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose}>
      <h2>New project</h2>
      <p className="muted small">Creating a project provisions its own Hindsight bank: missions, three guardrail directives and the Project Rulebook mental model.</p>
      <div className="stack" style={{ marginTop: 16 }}>
        <label className="field"><span>Name</span><input className="input" autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Checkout Service" /></label>
        <label className="field"><span>Description</span><textarea className="textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What the system does and where it runs" /></label>
        <label className="field"><span>Tech stack</span><input className="input" value={form.tech_stack} onChange={(e) => setForm({ ...form, tech_stack: e.target.value })} placeholder="Next.js, Prisma, Postgres…" /></label>
        <label className="field"><span>Areas</span><input className="input" value={form.areas} onChange={(e) => setForm({ ...form, areas: e.target.value })} /><small>Comma-separated. Used to group the Rulebook.</small></label>
        <div className="row"><Boxes size={14} className="muted" /><span className="tiny muted">Bank ID is generated server-side — clients can never choose a bank.</span><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={Sparkles} loading={m.isPending} disabled={form.name.trim().length < 2} onClick={() => m.mutate()}>Create & provision</Button></div>
      </div>
    </Modal>
  );
}
