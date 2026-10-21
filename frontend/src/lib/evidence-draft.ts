"use client";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { researchRequest, SAFE_REPLAY_AGE_MS } from "./research-request";
import type { components } from "./generated-contracts";
import type { Thread } from "./types";

export type Evidence = components["EvidencePublic"];
export type EvidenceOrigin = {
  paperId: string;
  fileId: string;
  version: number;
  page: number;
  hasText: boolean;
};
export type SelectionRect = {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
};
type Draft = {
  quote: string;
  interpretation: string;
  origin?: EvidenceOrigin;
  capture: "selected" | "manual";
  rects: SelectionRect[];
  target?: Pick<Thread, "id" | "title" | "project_id">;
};
type Attempt = {
  path: string;
  key: string;
  body: object;
  createdAt: number;
  uncertain: boolean;
};
const empty = (): Draft => ({
  quote: "",
  interpretation: "",
  capture: "manual",
  rects: [],
});

export function useEvidenceDraft(workspaceId: string) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState<Draft>(empty);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [saved, setSaved] = useState<Evidence>();
  const attempt = useRef<Attempt | null>(null);
  const busy = useRef(false);
  const uncertain = Boolean(attempt.current?.uncertain);
  const blocked = pending || uncertain || Boolean(saved);
  function capture(
    origin: EvidenceOrigin,
    quote: string,
    rects: SelectionRect[],
  ) {
    if (busy.current || blocked) return;
    setDraft((previous) => ({
      ...previous,
      origin,
      quote,
      rects,
      capture: "selected",
    }));
    setError(undefined);
  }
  function editQuote(quote: string, view?: EvidenceOrigin) {
    if (busy.current || blocked) return;
    setDraft((previous) => ({
      ...previous,
      quote,
      origin: previous.origin ?? view,
      rects: [],
      capture: "manual",
    }));
  }
  function explain(interpretation: string) {
    if (!busy.current && !blocked)
      setDraft((previous) => ({ ...previous, interpretation }));
  }
  function target(value?: Draft["target"]) {
    if (!busy.current && !blocked)
      setDraft((previous) => ({ ...previous, target: value }));
  }
  function reset() {
    if (busy.current || uncertain) return;
    setDraft((previous) => ({ ...empty(), target: previous.target }));
    setSaved(undefined);
    setError(undefined);
    attempt.current = null;
  }
  async function submit(replay = false) {
    if (busy.current || saved) return;
    if (
      attempt.current?.uncertain &&
      Date.now() - attempt.current.createdAt >= SAFE_REPLAY_AGE_MS
    ) {
      setError(
        new Error(
          "原请求已超过可安全重试时限。请先到原研究线索核对证据，再决定后续操作。",
        ),
      );
      return;
    }
    if (uncertain && !replay) return;
    if (!attempt.current?.uncertain) {
      if (!draft.origin || !draft.target) {
        setError(new Error("请在 PDF 渲染完成后摘录原文，并选择研究线索。"));
        return;
      }
      const origin = draft.origin;
      attempt.current = {
        path: `/threads/${draft.target.id}/evidence`,
        key: attempt.current?.key ?? crypto.randomUUID(),
        createdAt: Date.now(),
        uncertain: false,
        body: {
          paper_id: origin.paperId,
          paper_file_id: origin.fileId,
          quote_text: draft.quote,
          interpretation: draft.interpretation,
          source: {
            page_start: origin.page,
            page_end: origin.page,
            capture_method: draft.capture,
            rects: draft.rects,
            coordinate_space: "unrotated-cropbox-top-left-normalized",
          },
        },
      };
    }
    const request = attempt.current!;
    busy.current = true;
    setPending(true);
    setError(undefined);
    try {
      const result = await researchRequest<Evidence>(
        request.path,
        "POST",
        request.body,
        request.key,
      );
      setSaved(result.data);
      attempt.current = null;
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    } catch (reason) {
      setError(reason);
      if (!(
        reason instanceof ApiError &&
        ([400, 401, 403, 404, 405, 413, 415, 422, 429].includes(
          reason.status,
        ) ||
          reason.code === "SOURCE_UNAVAILABLE")
      ))
        request.uncertain = true;
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  return {
    draft,
    pending,
    error,
    saved,
    uncertain,
    blocked,
    capture,
    editQuote,
    explain,
    target,
    reset,
    submit: () => submit(),
    retry: () => submit(true),
  };
}
