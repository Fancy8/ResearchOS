"use client";
import { useId, useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { researchRequest, SAFE_REPLAY_AGE_MS } from "@/lib/research-request";
import { scopedKey } from "@/lib/query-client";
import { usePagedRows, type PageState } from "@/lib/pagination";
import type { Decision, Hypothesis, Note } from "@/lib/types";
import { ErrorBox, Loading } from "./common";
import { PaginationControls } from "./pagination-controls";
import { Button } from "./ui/button";

export type EditableDecision = {
  id: string;
  thread_id: string;
  title: string;
  decision_type: string;
  current_revision: number;
  revision: {
    reason: string;
    content: string;
    evidence: { evidence_id: string; quote_snapshot?: string }[];
    hypotheses: { hypothesis_id: string; statement_snapshot?: string }[];
    notes: { note_id: string; note_version: number }[];
  };
};
type BasisKind = "evidence_ids" | "hypothesis_ids" | "note_ids";
type Values = {
  title: string;
  decision_type: string;
  reason: string;
  content: string;
} & Record<BasisKind, string[]>;
type Labels = Record<BasisKind, Record<string, string>>;
type Attempt = {
  path: string;
  key: string;
  body: object;
  createdAt: number;
  uncertain: boolean;
};
function initial(item?: EditableDecision): Values {
  return {
    title: item?.title ?? "",
    decision_type: item?.decision_type ?? "adopt",
    reason: item?.revision.reason ?? "",
    content: item?.revision.content ?? "",
    evidence_ids: item?.revision.evidence.map((row) => row.evidence_id) ?? [],
    hypothesis_ids:
      item?.revision.hypotheses.map((row) => row.hypothesis_id) ?? [],
    note_ids: item?.revision.notes.map((row) => row.note_id) ?? [],
  };
}
function initialLabels(item?: EditableDecision): Labels {
  return {
    evidence_ids: Object.fromEntries(
      item?.revision.evidence.map((row) => [
        row.evidence_id,
        row.quote_snapshot ?? `已引用证据 ${row.evidence_id.slice(0, 8)}`,
      ]) ?? [],
    ),
    hypothesis_ids: Object.fromEntries(
      item?.revision.hypotheses.map((row) => [
        row.hypothesis_id,
        row.statement_snapshot ?? `已引用假设 ${row.hypothesis_id.slice(0, 8)}`,
      ]) ?? [],
    ),
    note_ids: Object.fromEntries(
      item?.revision.notes.map((row) => [
        row.note_id,
        `已引用笔记 ${row.note_id.slice(0, 8)}（v${row.note_version}）`,
      ]) ?? [],
    ),
  };
}

function BasisPicker({
  kind,
  label,
  pagingLabel,
  options,
  selected,
  labels,
  onChange,
  query,
  pending,
}: {
  kind: BasisKind;
  label: string;
  pagingLabel: string;
  options: Record<string, string>;
  selected: string[];
  labels: Record<string, string>;
  onChange: (id: string, label: string, checked: boolean) => void;
  query: PageState;
  pending: boolean;
}) {
  const id = useId();
  const entries = {
    ...options,
    ...Object.fromEntries(
      selected.map((value) => [
        value,
        labels[value] ??
          options[value] ??
          `已选记录 ${value.slice(0, 8)}（暂未重新加载）`,
      ]),
    ),
  };
  return (
    <section className="field decision-basis" aria-labelledby={id}>
      <strong id={id}>{label}</strong>
      <p className="muted">已选 {selected.length} 项（最多 100 项）</p>
      <div className="checkbox-options" role="group" aria-labelledby={id}>
        {Object.entries(entries).map(([value, text]) => (
          <label key={value}>
            <input
              type="checkbox"
              name={kind}
              value={value}
              checked={selected.includes(value)}
              disabled={!selected.includes(value) && selected.length >= 100}
              onChange={(event) => onChange(value, text, event.target.checked)}
            />
            {text}
          </label>
        ))}
      </div>
      {pending ? (
        <Loading />
      ) : (
        !Object.keys(entries).length &&
        !query.error && <p className="muted">当前没有可选择的记录</p>
      )}
      <PaginationControls query={query} label={pagingLabel} />
    </section>
  );
}

type Props = {
  workspaceId: string;
  threadId: string;
  item?: EditableDecision;
  onSaved?: () => Promise<void>;
};
function DecisionDialog({ workspaceId, threadId, item, onSaved }: Props) {
  const cache = useQueryClient();
  const modal = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [opened, setOpened] = useState(false);
  const [values, setValues] = useState<Values>(() => initial(item));
  const [labels, setLabels] = useState<Labels>(() => initialLabels(item));
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const draft = useRef(false);
  const baseline = useRef(item?.current_revision);
  const attempt = useRef<Attempt | null>(null);
  const [needsComparison, setNeedsComparison] = useState(false);
  const [conflict, setConflict] = useState<EditableDecision>();
  const [comparisonError, setComparisonError] = useState<unknown>();
  const [saved, setSaved] = useState<{ id: string; revision: number }>();
  const [refreshError, setRefreshError] = useState<unknown>();
  const [refreshPending, setRefreshPending] = useState(false);
  const evidence = usePagedRows<{ id: string; quote_text: string }>({
    queryKey: scopedKey(workspaceId, "decision-source-evidence", threadId),
    path: `/threads/${threadId}/evidence`,
    enabled: opened,
  });
  const hypotheses = usePagedRows<Hypothesis>({
    queryKey: scopedKey(workspaceId, "decision-source-hypotheses", threadId),
    path: `/threads/${threadId}/hypotheses`,
    enabled: opened,
  });
  const notes = usePagedRows<Note>({
    queryKey: scopedKey(workspaceId, "decision-source-notes"),
    path: "/notes",
    enabled: opened,
  });
  const uncertain = Boolean(attempt.current?.uncertain);
  function open() {
    if (!draft.current) {
      setValues(initial(item));
      setLabels(initialLabels(item));
      baseline.current = item?.current_revision;
      draft.current = true;
      setNeedsComparison(false);
      setConflict(undefined);
      setError(undefined);
    }
    setOpened(true);
    modal.current?.showModal();
    void evidence.refetch();
    void hypotheses.refetch();
    void notes.refetch();
  }
  function field(
    name: "title" | "decision_type" | "reason" | "content",
    value: string,
  ) {
    setValues((previous) => ({ ...previous, [name]: value }));
  }
  function select(
    kind: BasisKind,
    identifier: string,
    label: string,
    checked: boolean,
  ) {
    setLabels((previous) => ({
      ...previous,
      [kind]: { ...previous[kind], [identifier]: label },
    }));
    setValues((previous) => ({
      ...previous,
      [kind]: checked
        ? [...new Set([...previous[kind], identifier])]
        : previous[kind].filter((value) => value !== identifier),
    }));
  }
  async function refreshDetails() {
    if (!onSaved || refreshPending) return;
    setRefreshPending(true);
    setRefreshError(undefined);
    try {
      await onSaved();
    } catch (reason) {
      setRefreshError(reason);
    } finally {
      setRefreshPending(false);
    }
  }
  async function readComparison() {
    if (!item) return;
    setComparisonError(undefined);
    try {
      setConflict(
        (await researchRequest<EditableDecision>(`/decisions/${item.id}`)).data,
      );
    } catch (reason) {
      setComparisonError(reason);
    }
  }
  async function retryComparison() {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    try {
      await readComparison();
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  async function submit(replay = false) {
    if (busy.current || needsComparison) return;
    if (
      attempt.current?.uncertain &&
      Date.now() - attempt.current.createdAt >= SAFE_REPLAY_AGE_MS
    ) {
      setError(
        new Error(
          "原请求已超过可安全重试时限。请先核对决策及其历史，再决定后续操作。",
        ),
      );
      return;
    }
    if (!replay && uncertain) return;
    if (!attempt.current?.uncertain) {
      attempt.current = {
        path: item
          ? `/decisions/${item.id}/revisions`
          : `/threads/${threadId}/decisions`,
        key: attempt.current?.key ?? crypto.randomUUID(),
        createdAt: Date.now(),
        uncertain: false,
        body: {
          title: values.title.trim(),
          decision_type: values.decision_type,
          reason: values.reason.trim(),
          content: values.content,
          evidence_ids: [...values.evidence_ids].sort(),
          hypothesis_ids: [...values.hypothesis_ids].sort(),
          note_ids: [...values.note_ids].sort(),
          ...(item ? { expected_revision: baseline.current } : {}),
        },
      };
    }
    const request = attempt.current!;
    busy.current = true;
    setPending(true);
    setError(undefined);
    try {
      const result = await researchRequest<Decision>(
        request.path,
        "POST",
        request.body,
        request.key,
      );
      setSaved({ id: result.data.id, revision: result.data.current_revision });
      attempt.current = null;
      draft.current = false;
      setNeedsComparison(false);
      setConflict(undefined);
      modal.current?.close();
      setOpened(false);
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
      void refreshDetails();
    } catch (reason) {
      setError(reason);
      if (
        item &&
        reason instanceof ApiError &&
        reason.code === "VERSION_CONFLICT"
      ) {
        request.uncertain = false;
        setNeedsComparison(true);
        await readComparison();
      } else if (!(
        reason instanceof ApiError &&
        ([400, 401, 403, 404, 405, 413, 415, 422, 429].includes(
          reason.status,
        ) ||
          reason.code === "ASSOCIATION_CONFLICT")
      ))
        request.uncertain = true;
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  const title = item ? "修订研究决策（保留原版本）" : "记录研究决策";
  return (
    <>
      <button
        className="dialog-trigger"
        type="button"
        disabled={pending}
        onClick={open}
      >
        <span className={item ? "secondary-trigger" : "text-trigger"}>
          {item ? "记录新的决策版本" : "+ 记录判断"}
        </span>
      </button>
      {saved && (
        <p role="status" className="decision-save-confirmation">
          研究决策 v{saved.revision} 已保存。{" "}
          <Link href={`/decisions/${saved.id}?revision=${saved.revision}`}>
            查看已保存的决策版本
          </Link>
        </p>
      )}
      {Boolean(refreshError) && (
        <div className="decision-refresh-feedback">
          <p>保存已确认，详情暂未重新加载。重试只读取内容，不再提交决策。</p>
          <ErrorBox error={refreshError} />
          <Button
            type="button"
            variant="outline"
            disabled={refreshPending}
            onClick={refreshDetails}
          >
            重试读取决策
          </Button>
        </div>
      )}
      <dialog
        ref={modal}
        className="form-dialog"
        aria-labelledby={id}
        onClose={() => setOpened(false)}
      >
        <div className="dialog-heading">
          <h2 id={id}>{title}</h2>
          <Button
            type="button"
            variant="ghost"
            aria-label="关闭"
            onClick={() => modal.current?.close()}
          >
            ×
          </Button>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <fieldset className="research-fields" disabled={pending || uncertain}>
            <div className="field">
              <label htmlFor={`${id}-title`}>决策标题 *</label>
              <input
                id={`${id}-title`}
                value={values.title}
                maxLength={250}
                required
                onChange={(event) => field("title", event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`${id}-type`}>决策类型</label>
              <select
                id={`${id}-type`}
                value={values.decision_type}
                onChange={(event) => field("decision_type", event.target.value)}
              >
                <option value="adopt">采用</option>
                <option value="abandon">放弃</option>
                <option value="adjust">调整</option>
                <option value="defer">暂缓</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${id}-reason`}>
                {item ? "新的决策理由" : "为什么采取这个决定？"} *
              </label>
              <textarea
                id={`${id}-reason`}
                value={values.reason}
                maxLength={20000}
                required
                rows={4}
                onChange={(event) => field("reason", event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`${id}-content`}>
                {item ? "本次完整方案" : "具体方案"}
              </label>
              <textarea
                id={`${id}-content`}
                value={values.content}
                maxLength={50000}
                rows={4}
                onChange={(event) => field("content", event.target.value)}
              />
            </div>
            <p className="muted">
              依据摘要保留选择时的显示内容；实际快照以成功保存时的服务器版本为准。选项重新加载不会自动取消勾选。
            </p>
            <BasisPicker
              kind="evidence_ids"
              label={item ? "本次证据依据" : "本次依据：证据"}
              pagingLabel={item ? "可选证据" : "决策可选证据"}
              options={Object.fromEntries(
                evidence.data.data.map((row) => [
                  row.id,
                  row.quote_text.slice(0, 100),
                ]),
              )}
              selected={values.evidence_ids}
              labels={labels.evidence_ids}
              onChange={(id, label, checked) =>
                select("evidence_ids", id, label, checked)
              }
              query={evidence}
              pending={evidence.isPending}
            />
            <BasisPicker
              kind="hypothesis_ids"
              label={item ? "本次假设依据" : "本次依据：假设"}
              pagingLabel={item ? "可选假设" : "决策可选假设"}
              options={Object.fromEntries(
                hypotheses.data.data.map((row) => [row.id, row.statement]),
              )}
              selected={values.hypothesis_ids}
              labels={labels.hypothesis_ids}
              onChange={(id, label, checked) =>
                select("hypothesis_ids", id, label, checked)
              }
              query={hypotheses}
              pending={hypotheses.isPending}
            />
            <BasisPicker
              kind="note_ids"
              label={item ? "本次笔记依据" : "本次依据：笔记"}
              pagingLabel={item ? "可选笔记" : "决策可选笔记"}
              options={Object.fromEntries(
                notes.data.data.map((row) => [row.id, row.title]),
              )}
              selected={values.note_ids}
              labels={labels.note_ids}
              onChange={(id, label, checked) =>
                select("note_ids", id, label, checked)
              }
              query={notes}
              pending={notes.isPending}
            />
          </fieldset>
          {Boolean(error) && <ErrorBox error={error} />}
          {uncertain && (
            <div className="conflict-panel">
              <p>
                上次保存结果尚未确认，输入和依据选择已保留。请重试原请求核对结果，再进行新的修改。
              </p>
              <Button
                type="button"
                variant="outline"
                disabled={pending}
                onClick={() => submit(true)}
              >
                重试原请求
              </Button>
            </div>
          )}
          {needsComparison && (
            <section className="conflict-panel" aria-label="服务器决策版本">
              {conflict ? (
                <>
                  <h3>服务器已保存决策 v{conflict.current_revision}</h3>
                  <p>{conflict.title}</p>
                  <p>
                    类型：
                    {
                      {
                        adopt: "采用",
                        abandon: "放弃",
                        adjust: "调整",
                        defer: "暂缓",
                      }[conflict.decision_type]
                    }
                  </p>
                  <strong>服务器决策理由</strong>
                  <blockquote>{conflict.revision.reason}</blockquote>
                  <strong>服务器完整方案</strong>
                  <p className="decision-conflict-content">
                    {conflict.revision.content || "未记录方案细节"}
                  </p>
                  <p>
                    服务器依据：{conflict.revision.evidence.length} 条证据、
                    {conflict.revision.hypotheses.length} 个假设、
                    {conflict.revision.notes.length} 篇笔记。
                  </p>
                  <Link
                    href={`/decisions/${conflict.id}?revision=${conflict.current_revision}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    查看服务器决策版本及依据
                  </Link>
                  <p>
                    当前输入和勾选仍保留。请比较并手动合并，再明确采用这个版本作为修订基准。
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={pending}
                    onClick={() => {
                      baseline.current = conflict.current_revision;
                      attempt.current = null;
                      setNeedsComparison(false);
                      setConflict(undefined);
                      setError(undefined);
                    }}
                  >
                    采用服务器最新版本作为修订基准
                  </Button>
                </>
              ) : (
                <p>
                  版本已变化，需读取服务器版本后才能继续保存。当前输入仍保留。
                </p>
              )}
              {Boolean(comparisonError) && <ErrorBox error={comparisonError} />}
              <Button
                type="button"
                variant="outline"
                disabled={pending}
                onClick={retryComparison}
              >
                重新读取服务器版本
              </Button>
            </section>
          )}
          <div className="form-actions">
            <Button
              type="button"
              variant="outline"
              onClick={() => modal.current?.close()}
            >
              取消
            </Button>
            <Button
              type="submit"
              disabled={pending || uncertain || needsComparison}
            >
              {pending ? "保存中…" : "保存"}
            </Button>
          </div>
        </form>
      </dialog>
    </>
  );
}

export function DecisionCreator({
  workspaceId,
  threadId,
}: {
  workspaceId: string;
  threadId: string;
}) {
  return (
    <DecisionDialog
      key={threadId}
      workspaceId={workspaceId}
      threadId={threadId}
    />
  );
}
export function DecisionEditor({
  workspaceId,
  item,
  onSaved,
}: {
  workspaceId: string;
  item: EditableDecision;
  onSaved?: () => Promise<void>;
}) {
  return (
    <DecisionDialog
      key={item.id}
      workspaceId={workspaceId}
      threadId={item.thread_id}
      item={item}
      onSaved={onSaved}
    />
  );
}
