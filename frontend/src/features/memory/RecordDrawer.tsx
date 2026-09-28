/** Record drawer with full provenance (blueprint 9.6). Owner: P3. Mounted by the app shell. */
import { useProject } from "../../app/context";
import { ErrorCard, Skeleton, TypeBadge } from "../../components";
import { useRecord } from "./api";

export default function RecordDrawer({ recordId, onClose }: { recordId: string; onClose: () => void }) {
  const { projectId } = useProject();
  const record = useRecord(projectId, recordId);
  const r = record.data;
  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/20" onClick={onClose}>
      <aside
        role="dialog"
        aria-label="Record details"
        className="h-full w-full max-w-lg overflow-y-auto bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" onClick={onClose} className="float-right text-sm text-muted" aria-label="Close">
          Close
        </button>
        {record.isLoading && <Skeleton lines={8} />}
        {record.isError && <ErrorCard error={record.error} onRetry={() => record.refetch()} />}
        {r && (
          <div className="space-y-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs">{r.pill}</span>
              <TypeBadge type={r.type} />
              <span className="text-xs text-muted">{r.status}</span>
            </div>
            <h2 className="text-lg font-semibold">{r.title}</h2>
            <p>{r.statement}</p>
            {r.rationale && <p className="text-muted">Why: {r.rationale}</p>}
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <dt className="text-muted">Decided</dt><dd>{r.decided_at.slice(0, 10)}</dd>
              <dt className="text-muted">Approved by</dt><dd>{r.approved_by ?? "—"}</dd>
              <dt className="text-muted">Confidence</dt><dd>{r.confidence_band} ({r.stated_by})</dd>
              <dt className="text-muted">Hindsight doc</dt><dd className="font-mono">{r.hindsight_document_id}</dd>
              <dt className="text-muted">Sync</dt><dd>{r.retain_state}</dd>
              <dt className="text-muted">Versions</dt><dd>{r.version_chain.length}</dd>
            </dl>
            {r.evidence.length > 0 && (
              <section>
                <h3 className="mb-1 font-semibold">Evidence</h3>
                {r.evidence.map((e, i) => (
                  <blockquote key={i} className="mb-2 border-l-2 border-accent pl-2 italic">{e.quote}</blockquote>
                ))}
              </section>
            )}
            <section>
              <h3 className="mb-1 font-semibold">Retained content</h3>
              <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-paper p-2 font-mono text-xs">{r.retained_content}</pre>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}
