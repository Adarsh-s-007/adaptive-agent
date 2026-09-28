import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/** Any provenance pill opens the Record drawer by setting ?record=<id> in the URL. */
export function useRecordDrawer() {
  const [params, setParams] = useSearchParams();
  return useCallback(
    (recordId: string | null) => {
      const next = new URLSearchParams(params);
      if (recordId) next.set("record", recordId);
      else next.delete("record");
      setParams(next, { replace: false });
    },
    [params, setParams],
  );
}
