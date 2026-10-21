"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write } from "@/lib/api";
import { usePagedRows } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";
import { scopedKey } from "@/lib/query-client";
import { statuses, type User } from "@/lib/types";
import { Empty, ErrorBox, FormDialog, Heading, Loading } from "./common";
import { Button } from "./ui/button";
import { DecisionEditor } from "./decision-editor";

type HypothesisDetail = {
  id: string;
  thread_id: string;
  statement: string;
  status: string;
  version: number;
  evidence_links: {
    evidence_id: string;
    relation: string;
    explanation: string;
  }[];
};
const relations: Record<string, string> = {
  support: "支持性线索",
  challenge: "反面证据",
  background: "背景信息",
  uncertain: "暂不确定",
};

export function HypothesisDetailPage({
  user,
  identifier,
}: {
  user: User;
  identifier: string;
}) {
  const cache = useQueryClient();
  const [error, setError] = useState<unknown>();
  const result = useQuery({
    queryKey: scopedKey(user.workspace_id, "hypothesis-detail", identifier),
    queryFn: () => api<HypothesisDetail>(`/hypotheses/${identifier}`),
  });
  const history = usePagedRows<{
    id: string;
    revision_no: number;
    statement: string;
    status: string;
    created_at: string;
  }>({
    queryKey: scopedKey(user.workspace_id, "hypothesis-history", identifier),
    path: `/hypotheses/${identifier}/revisions`,
  });
  if (result.isPending) return <Loading />;
  if (result.error) return <ErrorBox error={result.error} />;
  const item = result.data.data;
  const refresh = () =>
    cache.invalidateQueries({ queryKey: ["workspace", user.workspace_id] });
  return (
    <>
      <Link href={`/threads/${item.thread_id}`} className="breadcrumb">
        返回研究线索
      </Link>
      <Heading
        eyebrow="RESEARCH HYPOTHESIS"
        title="研究假设与证据判断"
        text={item.statement}
        action={
          <FormDialog
            title="编辑研究假设"
            trigger={<span className="secondary-trigger">编辑假设</span>}
            fields={[
              {
                name: "statement",
                label: "研究判断",
                type: "textarea",
                default: item.statement,
              },
              {
                name: "status",
                label: "当前验证状态",
                type: "select",
                default: item.status,
                options: Object.fromEntries(
                  [
                    "proposed",
                    "testing",
                    "supported",
                    "contradicted",
                    "inconclusive",
                  ].map((value) => [value, statuses[value]]),
                ),
              },
            ]}
            onSubmit={async (values) => {
              await write(`/hypotheses/${identifier}`, "PATCH", {
                ...values,
                expected_version: item.version,
              });
              refresh();
            }}
          />
        }
      />
      {Boolean(error) && <ErrorBox error={error} />}
      <section className="panel">
        <div className="panel-heading">
          <h2>当前关联证据</h2>
          <span className="badge">{statuses[item.status]}</span>
        </div>
        {item.evidence_links.length ? (
          item.evidence_links.map((link) => (
            <div className="record-card" key={link.evidence_id}>
              <Link
                className="open-link"
                href={`/evidence/${link.evidence_id}`}
              >
                查看原始证据 →
              </Link>
              <p>
                {relations[link.relation]} ·{" "}
                {link.explanation || "未补充关系判断"}
              </p>
              <div className="record-actions">
                <FormDialog
                  title="修改证据关系"
                  trigger={<span className="secondary-trigger">编辑关系</span>}
                  fields={[
                    {
                      name: "relation",
                      label: "证据关系",
                      type: "select",
                      options: relations,
                      default: link.relation,
                    },
                    {
                      name: "explanation",
                      label: "我的解释",
                      type: "textarea",
                      default: link.explanation,
                      required: false,
                    },
                  ]}
                  onSubmit={async (values) => {
                    await write(
                      `/hypotheses/${identifier}/evidence-links/${link.evidence_id}`,
                      "PATCH",
                      {
                        ...values,
                        evidence_id: link.evidence_id,
                        expected_version: item.version,
                      },
                    );
                    refresh();
                  }}
                />
                <Button
                  variant="ghost"
                  onClick={async () => {
                    try {
                      await write(
                        `/hypotheses/${identifier}/evidence-links/${link.evidence_id}`,
                        "DELETE",
                        { expected_version: item.version },
                      );
                      refresh();
                    } catch (reason) {
                      setError(reason);
                    }
                  }}
                >
                  移除关联（保留证据）
                </Button>
              </div>
            </div>
          ))
        ) : (
          <Empty
            title="尚未关联证据"
            text="从研究线索为假设关联支持、反面、背景或不确定的证据。"
          />
        )}
      </section>
      <section className="panel">
        <h2>判断历史</h2>
        {history.error ? (
          <ErrorBox error={history.error} />
        ) : (
          history.data?.data.map((row) => (
            <div className="record-card" key={row.id}>
              <span className="badge">
                v{row.revision_no} · {statuses[row.status]}
              </span>
              <p>{row.statement}</p>
              <small>{new Date(row.created_at).toLocaleString("zh-CN")}</small>
            </div>
          ))
        )}
        <PaginationControls query={history} label="假设历史" />
      </section>
    </>
  );
}

type EvidenceDetail = {
  id: string;
  thread_id: string;
  quote_text: string;
  interpretation: string;
  paper_id: string;
  paper_file_id: string;
  page_start: number;
  page_end: number;
  anchor_status: string;
  version: number;
};

export function EvidenceDetailPage({
  user,
  identifier,
}: {
  user: User;
  identifier: string;
}) {
  const cache = useQueryClient();
  const result = useQuery({
    queryKey: scopedKey(user.workspace_id, "evidence-detail", identifier),
    queryFn: () => api<EvidenceDetail>(`/evidence/${identifier}`),
  });
  if (result.isPending) return <Loading />;
  if (result.error) return <ErrorBox error={result.error} />;
  const item = result.data.data;
  return (
    <>
      <Link className="breadcrumb" href={`/threads/${item.thread_id}`}>
        返回研究线索
      </Link>
      <Heading
        eyebrow="SOURCE EVIDENCE"
        title="研究证据"
        text={`原始来源 · 第 ${item.page_start}${item.page_end !== item.page_start ? `–${item.page_end}` : ""} 页`}
        action={
          <Button asChild>
            <Link
              href={`/papers/${item.paper_id}?fileId=${item.paper_file_id}&page=${item.page_start}&evidenceId=${item.id}`}
            >
              打开原始 PDF 位置
            </Link>
          </Button>
        }
      />
      <section className="panel evidence-card">
        <span className="badge">
          {item.anchor_status === "located"
            ? "原文可核验"
            : item.anchor_status === "page_only"
              ? "页码级定位"
              : "来源待处理"}
        </span>
        <blockquote>{item.quote_text}</blockquote>
        <h2>我的解释</h2>
        <p>{item.interpretation || "尚未记录解释"}</p>
        <FormDialog
          title="编辑证据解释"
          trigger={<span className="secondary-trigger">编辑解释</span>}
          fields={[
            {
              name: "interpretation",
              label: "我的解释",
              type: "textarea",
              default: item.interpretation,
              required: false,
            },
          ]}
          onSubmit={async (values) => {
            await write(`/evidence/${identifier}`, "PATCH", {
              ...values,
              expected_version: item.version,
            });
            cache.invalidateQueries({
              queryKey: ["workspace", user.workspace_id],
            });
          }}
        />
      </section>
    </>
  );
}

type Revision = {
  revision_no: number;
  title_snapshot: string;
  reason: string;
  content: string;
  evidence: {
    evidence_id: string;
    quote_snapshot: string;
    interpretation_snapshot: string;
  }[];
  hypotheses: {
    hypothesis_id: string;
    statement_snapshot: string;
    status_snapshot: string;
  }[];
  notes: {
    note_id: string;
    note_version: number;
    content_snapshot: Record<string, unknown>;
  }[];
};
type Decision = {
  id: string;
  thread_id: string;
  title: string;
  decision_type: string;
  current_revision: number;
  revision: Revision;
};

export function DecisionDetailPage({
  user,
  identifier,
}: {
  user: User;
  identifier: string;
}) {
  const parameters = useSearchParams();
  const [selected, setSelected] = useState(
    Number(parameters.get("revision")) || 0,
  );
  const result = useQuery({
    queryKey: scopedKey(user.workspace_id, "decision-detail", identifier),
    queryFn: () => api<Decision>(`/decisions/${identifier}`),
  });
  const versions = usePagedRows<{ id: string; revision_no: number }>({
    queryKey: scopedKey(user.workspace_id, "decision-versions", identifier),
    path: `/decisions/${identifier}/revisions`,
  });
  const history = useQuery({
    queryKey: scopedKey(
      user.workspace_id,
      "decision-detail-revision",
      identifier,
      selected,
    ),
    queryFn: () =>
      api<Revision>(`/decisions/${identifier}/revisions/${selected}`),
    enabled: selected > 0,
  });
  useEffect(
    () => setSelected(Number(parameters.get("revision")) || 0),
    [parameters],
  );
  if (result.isPending) return <Loading />;
  if (result.error && !result.data)
    return <ErrorBox error={result.error} retry={() => result.refetch()} />;
  const item = result.data!.data;
  const revision = selected ? history.data?.data : item.revision;
  return (
    <>
      <Link className="breadcrumb" href={`/threads/${item.thread_id}`}>
        返回研究线索
      </Link>
      <Heading
        eyebrow="RESEARCH DECISION"
        title={revision?.title_snapshot ?? item.title}
        text="查看当时的判断与依据；后续修改不会覆盖这个版本。"
      />
      <section className="panel">
        <DecisionEditor workspaceId={user.workspace_id} item={item} />
        {Boolean(result.error) && (
          <ErrorBox error={result.error} retry={() => result.refetch()} />
        )}
        {Boolean(history.error) && (
          <ErrorBox error={history.error} retry={() => history.refetch()} />
        )}
        <label className="field">
          决策版本
          <select
            aria-label="决策版本"
            value={selected || item.current_revision}
            onChange={(event) => setSelected(Number(event.target.value))}
          >
            {[
              ...new Set([
                item.current_revision,
                ...(selected ? [selected] : []),
                ...versions.data.data.map((row) => row.revision_no),
              ]),
            ]
              .sort((a, b) => b - a)
              .map((version) => (
                <option key={version} value={version}>
                  v{version}
                </option>
              ))}
          </select>
        </label>
        <PaginationControls query={versions} label="决策历史版本" />
        {revision ? (
          <div className="decision-reason">
            <strong>决策理由</strong>
            <p>{revision.reason}</p>
            <strong>具体方案</strong>
            <p>{revision.content || "未记录方案细节"}</p>
            <strong>当时的证据</strong>
            {revision.evidence.map((source) => (
              <blockquote key={source.evidence_id}>
                {source.quote_snapshot}
                <small>{source.interpretation_snapshot}</small>
                <Link href={`/evidence/${source.evidence_id}`}>查看来源 →</Link>
              </blockquote>
            ))}
            <strong>当时的假设</strong>
            {revision.hypotheses.map((source) => (
              <p key={source.hypothesis_id}>
                {source.statement_snapshot} · {statuses[source.status_snapshot]}
              </p>
            ))}
            <strong>当时的笔记</strong>
            {revision.notes.map((source) => (
              <blockquote key={source.note_id}>
                笔记 v{source.note_version}
                <p>{plainNote(source.content_snapshot)}</p>
                <Link href={`/notes/${source.note_id}`}>
                  查看当前笔记（可能已经更新） →
                </Link>
              </blockquote>
            ))}
          </div>
        ) : (
          <Loading />
        )}
      </section>
    </>
  );
}

function plainNote(value: Record<string, unknown>): string {
  if (["inlineMath", "blockMath"].includes(String(value.type)))
    return String((value.attrs as { latex?: string } | undefined)?.latex ?? "");
  if (typeof value.text === "string") return value.text;
  return Array.isArray(value.content)
    ? value.content
        .map((child) => plainNote(child as Record<string, unknown>))
        .join("\n")
    : "";
}
