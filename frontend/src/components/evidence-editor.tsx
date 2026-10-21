"use client";
import Link from "next/link";
import type { Thread } from "@/lib/types";
import type { PageState } from "@/lib/pagination";
import {
  useEvidenceDraft,
  type EvidenceOrigin,
  type Evidence,
} from "@/lib/evidence-draft";
import { ErrorBox } from "./common";
import { PaginationControls } from "./pagination-controls";
import { Button } from "./ui/button";

export function EvidenceEditor({
  action,
  view,
  lines,
  source,
  highlightStatus,
}: {
  action: ReturnType<typeof useEvidenceDraft>;
  view?: EvidenceOrigin;
  lines: PageState & { data: { data: Thread[] } };
  source?: Evidence;
  highlightStatus: string;
}) {
  const { draft, blocked, saved } = action;
  const options = [
    ...new Map(
      [...(draft.target ? [draft.target] : []), ...lines.data.data].map(
        (row) => [row.id, row],
      ),
    ).values(),
  ];
  const different =
    draft.origin &&
    view &&
    (draft.origin.fileId !== view.fileId || draft.origin.page !== view.page);
  return (
    <aside className="evidence-editor" aria-label="创建研究证据">
      <h2>创建研究证据</h2>
      <p>
        {view?.hasText === false
          ? "扫描 PDF：可以手动录入摘录，保存为页码级证据。"
          : "选中原文，记录它与研究问题的关系。"}
      </p>
      {source && (
        <div className="source-evidence">
          <strong>正在回看原始证据 · 第 {source.page_start} 页</strong>
          <blockquote>{source.quote_text}</blockquote>
          <span>{highlightStatus}</span>
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void action.submit();
        }}
      >
        <fieldset className="research-fields" disabled={blocked}>
          <label className="field">
            原文摘录
            <textarea
              aria-label="原文摘录"
              rows={6}
              required
              maxLength={50000}
              value={draft.quote}
              disabled={!draft.origin && !view}
              onChange={(event) => action.editQuote(event.target.value, view)}
            />
          </label>
          <div className="source-location" aria-label="摘录出处">
            {draft.origin
              ? `文件 v${draft.origin.version} · 第 ${draft.origin.page} 页 · ${draft.capture === "selected" ? "选中文本待校验" : "人工录入"}`
              : "请等待 PDF 渲染完成后摘录"}
          </div>
          {different && (
            <p className="evidence-context-notice" role="status">
              当前阅读页已改变，草稿仍保留原文件与页码。若要更换出处，请重新开始摘录。
            </p>
          )}
          <label className="field">
            关联研究线索
            <select
              aria-label="关联研究线索"
              value={draft.target?.id ?? ""}
              required
              onChange={(event) =>
                action.target(
                  options.find((row) => row.id === event.target.value),
                )
              }
            >
              <option value="">请选择一个研究问题</option>
              {options.map((line) => (
                <option key={line.id} value={line.id}>
                  {line.title}
                </option>
              ))}
            </select>
          </label>
          <PaginationControls query={lines} label="阅读器研究线索" />
          <label className="field">
            我的理解
            <textarea
              aria-label="我的理解"
              rows={3}
              maxLength={20000}
              value={draft.interpretation}
              onChange={(event) => action.explain(event.target.value)}
            />
          </label>
          <Button
            type="submit"
            className="wide-button"
            disabled={!draft.target || !draft.origin}
          >
            {action.pending ? "正在保存…" : "保存研究证据"}
          </Button>
        </fieldset>
      </form>
      {Boolean(action.error) && <ErrorBox error={action.error} />}
      {action.uncertain && (
        <div className="evidence-retry-feedback">
          <p>
            上次保存结果尚未确认，原文、解释、出处和线索已保留。重试始终提交原请求。
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={action.pending}
            onClick={action.retry}
          >
            重试原请求
          </Button>
          {draft.target && (
            <Link
              href={`/threads/${draft.target.id}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              在新窗口核对原研究线索
            </Link>
          )}
        </div>
      )}
      {saved && (
        <div className="saved-evidence" role="status">
          证据已保存 ·{" "}
          {saved.anchor_status === "located" ? "原文可定位" : "页码级定位"}
          <Link href={`/threads/${saved.thread_id}`}>回到研究线索 →</Link>
          <Link href={`/evidence/${saved.id}`}>查看证据详情</Link>
        </div>
      )}
      {!action.pending && !action.uncertain && (
        <Button
          type="button"
          variant="outline"
          disabled={!view}
          onClick={action.reset}
        >
          {saved ? "继续摘录下一条证据" : "重新开始摘录"}
        </Button>
      )}
    </aside>
  );
}
