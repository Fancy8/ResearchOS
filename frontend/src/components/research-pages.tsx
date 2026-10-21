"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  FileText,
  GitBranch,
  Plus,
  SquareCheck,
  History,
} from "lucide-react";
import { api, write } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import { usePagedRows, type PageState } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";
import {
  stages,
  statuses,
  events,
  type Activity,
  type Dashboard,
  type Decision,
  type Hypothesis,
  type Note,
  type Project,
  type Task,
  type Thread,
  type User,
} from "@/lib/types";
import { Button } from "./ui/button";
import {
  Empty,
  ErrorBox,
  FormDialog,
  Heading,
  Loading,
  OpenLink,
  type Field,
} from "./common";
import { LibraryPage } from "./library";
import { PdfReader } from "./pdf-reader";
import { NotePage, NotesPage } from "./notes";
import { ProfilePage } from "./profile";
import { DataSettings } from "./data-settings";
import { TaskDetail } from "./task-detail";
import { TaskRows } from "./task-actions";
import { TasksPage } from "./tasks";
import { TaskDialog } from "./task-dialog";
import { OnboardingPage } from "./onboarding";
import { researchRequest } from "@/lib/research-request";
import { DecisionEditor, DecisionCreator } from "./decision-editor";
import { ResearchCreateDialog } from "./research-create-dialog";
import {
  DecisionDetailPage,
  EvidenceDetailPage,
  HypothesisDetailPage,
} from "./object-detail";
import { objectPath } from "@/lib/navigation";

type Context = {
  user: User;
  current?: Project;
  projects: Project[];
  projectPaging?: PageState;
};
type EvidenceRecord = {
  id: string;
  quote_text: string;
  interpretation: string;
  paper_id: string;
  paper_file_id: string;
  page_start: number;
  anchor_status: string;
  version: number;
};
type DecisionRevision = {
  revision_no: number;
  title_snapshot: string;
  decision_type_snapshot: string;
  reason: string;
  content: string;
  evidence: {
    evidence_id: string;
    paper_file_id: string;
    page_start: number;
    quote_snapshot: string;
    interpretation_snapshot: string;
  }[];
  hypotheses: {
    hypothesis_id: string;
    statement_snapshot: string;
    status_snapshot: string;
  }[];
  notes: { note_id: string; note_version: number }[];
};
type DecisionDetail = Omit<Decision, "revision"> & {
  revision: DecisionRevision;
};
const projectFields: Field[] = [
  { name: "title", label: "课题名称" },
  {
    name: "description",
    label: "研究目标与背景",
    type: "textarea",
    required: false,
  },
  {
    name: "research_stage",
    label: "当前研究阶段",
    type: "select",
    options: stages,
  },
];
const threadFields: Field[] = [
  { name: "title", label: "研究线索标题" },
  { name: "question", label: "你希望解决什么研究问题？", type: "textarea" },
  { name: "description", label: "问题背景", type: "textarea", required: false },
];
const addTrigger = (label: string) => (
  <span className="primary-trigger">
    <Plus size={17} />
    {label}
  </span>
);

function useRefresh(workspace: string) {
  const cache = useQueryClient();
  return () => cache.invalidateQueries({ queryKey: ["workspace", workspace] });
}
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge status-${status}`}>
      {statuses[status] ?? status}
    </span>
  );
}

function ThreadCard({ thread }: { thread: Thread }) {
  return (
    <Link className="thread-card" href={`/threads/${thread.id}`}>
      <div className="thread-icon">
        <GitBranch size={20} />
      </div>
      <div>
        <div className="card-label">
          研究线索 <Badge status={thread.status} />
        </div>
        <h3>{thread.title}</h3>
        <p>{thread.question}</p>
      </div>
      <ArrowRight size={18} />
    </Link>
  );
}
function ActivityRows({ items }: { items: Activity[] }) {
  return (
    <div className="activity-rows">
      {items.map((item) => (
        <div className="activity-row" key={item.id}>
          <span className="activity-dot" />
          <div>
            <Link
              href={
                objectPath(item.target_type, item.target_id) +
                (item.target_type === "research_decisions" &&
                item.event_payload?.revision_no
                  ? `?revision=${item.event_payload.revision_no}`
                  : "")
              }
            >
              {events[item.event_type] ?? item.event_type}
            </Link>
            <small>
              {new Date(item.created_at).toLocaleString("zh-CN", {
                timeZone: "Asia/Hong_Kong",
                hour12: false,
              })}
            </small>
          </div>
        </div>
      ))}
    </div>
  );
}

function DashboardPage({ user, current }: Context) {
  const refresh = useRefresh(user.workspace_id);
  const data = useQuery({
    queryKey: scopedKey(user.workspace_id, "dashboard", current?.id),
    queryFn: () =>
      api<Dashboard>(`/dashboard${current ? `?project_id=${current.id}` : ""}`),
  });
  if (data.isPending) return <Loading />;
  if (data.error)
    return <ErrorBox error={data.error} retry={() => data.refetch()} />;
  const value = data.data.data;
  const modules: Record<string, React.ReactNode> = {
    threads: (
      <section className="panel">
        <div className="panel-heading">
          <h2>
            <GitBranch size={18} />
            值得继续的问题
          </h2>
          <OpenLink href="/projects">全部课题</OpenLink>
        </div>
        {value.threads.length ? (
          value.threads.map((thread) => (
            <ThreadCard key={thread.id} thread={thread} />
          ))
        ) : (
          <Empty
            title="从一个研究问题开始"
            text="建立线索，将后续证据、判断和行动连接起来。"
            action={
              <Button asChild>
                <Link href={current ? `/projects/${current.id}` : "/projects"}>
                  创建研究线索
                </Link>
              </Button>
            }
          />
        )}
      </section>
    ),
    tasks: (
      <section className="panel">
        <div className="panel-heading">
          <h2>
            <SquareCheck size={18} />
            下一步行动
          </h2>
          <OpenLink href="/tasks">所有任务</OpenLink>
        </div>
        {value.tasks.length ? (
          <TaskRows tasks={value.tasks} workspaceId={user.workspace_id} />
        ) : (
          <Empty
            title="下一步，做什么？"
            text="从研究决策创建任务，把思考转为行动。"
          />
        )}
      </section>
    ),
    activity: (
      <section className="panel">
        <div className="panel-heading">
          <h2>
            <History size={18} />
            最近研究活动
          </h2>
          <OpenLink href="/activity">查看日志</OpenLink>
        </div>
        {value.activity.length ? (
          <ActivityRows items={value.activity} />
        ) : (
          <Empty
            title="研究的轨迹会留在这里"
            text="创建线索、记录判断或完成任务后，会出现真实研究记录。"
          />
        )}
      </section>
    ),
  };
  return (
    <>
      <Heading
        eyebrow="YOUR RESEARCH, CONNECTED"
        title={`${user.display_name}，继续你的研究`}
        text="把注意力留给值得解决的问题，让每一步都有依据。"
        action={
          <Button asChild variant="outline">
            <Link href="/projects">
              管理研究课题 <ArrowRight size={16} />
            </Link>
          </Button>
        }
      />
      <section className="focus-banner">
        <div>
          <div className="focus-label">
            <span />
            当前研究焦点
          </div>
          <h2>{value.project?.title ?? "开启你的第一个研究课题"}</h2>
          <p>
            {value.project?.description ||
              "一个明确的问题，是一段研究旅程的起点。"}
          </p>
        </div>
        <div className="focus-stage">
          <span>当前阶段</span>
          <strong>
            {value.project ? stages[value.project.research_stage] : "待设置"}
          </strong>
          <Link
            href={
              value.project ? `/projects/${value.project.id}` : "/onboarding"
            }
          >
            查看课题 <ArrowRight size={15} />
          </Link>
        </div>
      </section>
      <div className="stats-row">
        {[
          ["threads", "研究线索", GitBranch],
          ["evidence", "原文证据", BookOpen],
          ["hypotheses", "研究假设", FileText],
          ["tasks", "科研任务", SquareCheck],
        ].map(([key, label, Icon]) => {
          const Symbol = Icon as typeof GitBranch;
          return (
            <div className="stat" key={String(key)}>
              <Symbol size={19} />
              <strong>{value.counts[String(key)] ?? 0}</strong>
              <span>{String(label)}</span>
            </div>
          );
        })}
      </div>
      <div className="dashboard-grid">
        {value.module_order.map((key) => (
          <div className={`module-${key}`} key={key}>
            {modules[key]}
          </div>
        ))}
      </div>
    </>
  );
}

function ProjectsPage({ user, projects, projectPaging }: Context) {
  return (
    <>
      <Heading
        eyebrow="RESEARCH PROJECTS"
        title="我的研究课题"
        text="不同方向，独立推进。资料和历史会持续保留。"
        action={
          <ResearchCreateDialog
            workspaceId={user.workspace_id}
            kind="project"
            title="创建研究课题"
            trigger={addTrigger("新建课题")}
            fields={projectFields}
          />
        }
      />
      {projects.length ? (
        <div className="project-grid">
          {projects.map((item) => (
            <Link
              className="project-card"
              href={`/projects/${item.id}`}
              key={item.id}
            >
              <div className="project-card-top">
                <div className="thread-icon">
                  <GitBranch size={20} />
                </div>
                <Badge status={item.status} />
              </div>
              <h2>{item.title}</h2>
              <p>{item.description || "尚未填写研究目标"}</p>
              <div className="project-card-bottom">
                <span>{stages[item.research_stage]}</span>
                <span>
                  {item.is_default ? "默认课题" : "打开课题"}{" "}
                  <ArrowRight size={15} />
                </span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <Empty
          title="给你的研究一个起点"
          text="创建课题，再围绕具体问题建立研究线索。"
        />
      )}
      {projectPaging && (
        <PaginationControls query={projectPaging} label="课题" />
      )}
    </>
  );
}

function ProjectPage({ user, identifier }: Context & { identifier: string }) {
  const refresh = useRefresh(user.workspace_id);
  const item = useQuery({
    queryKey: scopedKey(user.workspace_id, "project", identifier),
    queryFn: () => api<Project>(`/projects/${identifier}`),
  });
  const lines = usePagedRows<Thread>({
    queryKey: scopedKey(user.workspace_id, "threads", identifier),
    path: `/projects/${identifier}/threads`,
  });
  const linkedPapers = usePagedRows<{ id: string; title: string }>({
    queryKey: scopedKey(user.workspace_id, "project-papers", identifier),
    path: `/projects/${identifier}/paper-links`,
  });
  const linkedNotes = usePagedRows<{ id: string; title: string }>({
    queryKey: scopedKey(user.workspace_id, "project-notes", identifier),
    path: `/projects/${identifier}/note-links`,
  });
  if (item.isPending || lines.isPending) return <Loading />;
  if (item.error || lines.error)
    return <ErrorBox error={item.error ?? lines.error} />;
  const project = item.data.data;
  return (
    <>
      <Link className="breadcrumb" href="/projects">
        研究课题 / {project.title}
      </Link>
      <Heading
        eyebrow="PROJECT OVERVIEW"
        title={project.title}
        text={
          project.description || "围绕这个课题，建立能够持续推进的研究问题。"
        }
        action={
          <ResearchCreateDialog
            workspaceId={user.workspace_id}
            kind="thread"
            parent={{ id: identifier, title: project.title }}
            title="新增研究线索"
            trigger={addTrigger("新增线索")}
            fields={threadFields}
          />
        }
      />
      <div className="project-settings">
        <Badge status={project.status} />
        <label>
          研究阶段
          <select
            value={project.research_stage}
            onChange={async (event) => {
              await write(`/projects/${identifier}`, "PATCH", {
                expected_version: project.version,
                research_stage: event.target.value,
              });
              refresh();
            }}
          >
            {Object.entries(stages).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <FormDialog
          title="编辑课题"
          trigger={<span className="secondary-trigger">编辑目标</span>}
          fields={projectFields.map((field) => ({
            ...field,
            default: String(project[field.name as keyof Project] ?? ""),
          }))}
          onSubmit={async (values) => {
            await write(`/projects/${identifier}`, "PATCH", {
              ...values,
              expected_version: project.version,
            });
            refresh();
          }}
        />
        <Button
          variant="outline"
          onClick={async () => {
            await write(`/projects/${identifier}/set-default`, "POST", {});
            refresh();
          }}
          disabled={project.is_default || project.status === "archived"}
        >
          设为默认
        </Button>
        <Button
          variant="ghost"
          onClick={async () => {
            await write(`/projects/${identifier}`, "PATCH", {
              expected_version: project.version,
              status: project.status === "archived" ? "active" : "archived",
            });
            refresh();
          }}
        >
          {project.status === "archived" ? "恢复课题" : "归档课题"}
        </Button>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>研究线索</h2>
          <span className="muted">问题 → 证据 → 判断 → 行动</span>
        </div>
        {lines.data.data.length ? (
          lines.data.data.map((line) => (
            <ThreadCard thread={line} key={line.id} />
          ))
        ) : (
          <Empty
            title="你正在解决什么问题？"
            text="一条研究线索连接一个问题，以及与之相关的资料、判断和任务。"
          />
        )}
        <PaginationControls query={lines} label="研究线索" />
      </section>
      <div className="project-assets">
        <section className="panel">
          <div className="panel-heading">
            <h2>关联文献</h2>
            <OpenLink href="/library">文献库</OpenLink>
          </div>
          {linkedPapers.error ? (
            <ErrorBox error={linkedPapers.error} />
          ) : (
            linkedPapers.data?.data.map((paper) => (
              <div className="linked-asset" key={paper.id}>
                <Link href={`/papers/${paper.id}`}>{paper.title}</Link>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    try {
                      await write(
                        `/projects/${identifier}/paper-links/${paper.id}`,
                        "DELETE",
                        {},
                      );
                      refresh();
                    } catch (error) {
                      window.alert(
                        error instanceof Error ? error.message : "移除失败",
                      );
                    }
                  }}
                >
                  仅移除关联
                </Button>
              </div>
            ))
          )}
          {linkedPapers.data?.data.length === 0 && (
            <p className="muted">上传文献或从证据引用后，可在这里找到它。</p>
          )}
          <PaginationControls query={linkedPapers} label="关联文献" />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>关联笔记</h2>
            <OpenLink href="/notes">科研笔记</OpenLink>
          </div>
          {linkedNotes.error ? (
            <ErrorBox error={linkedNotes.error} />
          ) : (
            linkedNotes.data?.data.map((note) => (
              <Link
                className="linked-asset"
                key={note.id}
                href={`/notes/${note.id}`}
              >
                {note.title}
              </Link>
            ))
          )}
          {linkedNotes.data?.data.length === 0 && (
            <p className="muted">在笔记关联面板中选择这个课题。</p>
          )}
          <PaginationControls query={linkedNotes} label="关联笔记" />
        </section>
      </div>
    </>
  );
}

function ThreadPage({ user, identifier }: Context & { identifier: string }) {
  const refresh = useRefresh(user.workspace_id);
  const line = useQuery({
    queryKey: scopedKey(user.workspace_id, "thread", identifier),
    queryFn: () => api<Thread>(`/threads/${identifier}`),
  });
  const hypotheses = usePagedRows<Hypothesis>({
    queryKey: scopedKey(user.workspace_id, "hypotheses", identifier),
    path: `/threads/${identifier}/hypotheses`,
  });
  const evidence = usePagedRows<EvidenceRecord>({
    queryKey: scopedKey(user.workspace_id, "evidence", identifier),
    path: `/threads/${identifier}/evidence`,
  });
  const decisions = usePagedRows<Decision>({
    queryKey: scopedKey(user.workspace_id, "decisions", identifier),
    path: `/threads/${identifier}/decisions`,
  });
  const tasks = usePagedRows<Task>({
    queryKey: scopedKey(user.workspace_id, "tasks", identifier),
    path: `/tasks?thread_id=${identifier}`,
  });
  const [showHistory, setShowHistory] = useState(false);
  const history = usePagedRows<{
    id: string;
    revision_no: number;
    title: string;
    question: string;
    created_at: string;
  }>({
    queryKey: scopedKey(user.workspace_id, "thread-history", identifier),
    path: `/threads/${identifier}/revisions`,
    enabled: showHistory,
  });
  const [detail, setDetail] = useState<unknown>();
  if (line.isPending) return <Loading />;
  if (line.error) return <ErrorBox error={line.error} />;
  const thread = line.data.data;
  return (
    <>
      <Link className="breadcrumb" href={`/projects/${thread.project_id}`}>
        研究课题 / 研究线索
      </Link>
      <Heading
        eyebrow="RESEARCH THREAD"
        title={thread.title}
        text={thread.question}
        action={
          <FormDialog
            title="编辑研究问题（保留历史）"
            trigger={<span className="secondary-trigger">编辑问题</span>}
            fields={threadFields.map((field) => ({
              ...field,
              default: String(thread[field.name as keyof Thread] ?? ""),
            }))}
            onSubmit={async (values) => {
              await write(`/threads/${identifier}`, "PATCH", {
                ...values,
                expected_version: thread.version,
              });
              refresh();
            }}
          />
        }
      />
      <div className="thread-meta">
        <Badge status={thread.status} />
        <span>问题版本 v{thread.current_revision}</span>
        <button
          className="text-button"
          onClick={() => setShowHistory((value) => !value)}
        >
          查看问题历史
        </button>
      </div>
      {showHistory && (
        <section className="panel">
          <h2>研究问题历史</h2>
          {history.error && <ErrorBox error={history.error} />}
          {history.data.data.map((row) => (
            <div className="record-card" key={row.id}>
              <span className="badge">问题 v{row.revision_no}</span>
              <h3>{row.title}</h3>
              <p>{row.question}</p>
              <small>{new Date(row.created_at).toLocaleString("zh-CN")}</small>
            </div>
          ))}
          <PaginationControls query={history} label="问题历史" />
        </section>
      )}
      <div className="workflow-layout">
        <div>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <BookOpen size={18} />
                已有证据
              </h2>
              <OpenLink href="/library">从文献摘录</OpenLink>
            </div>
            {evidence.error ? (
              <ErrorBox error={evidence.error} />
            ) : evidence.data?.data.length ? (
              evidence.data.data.map((item) => (
                <div className="evidence-card" key={item.id}>
                  <blockquote>{item.quote_text}</blockquote>
                  <p>{item.interpretation || "尚未添加用户解释"}</p>
                  <div className="record-actions">
                    <span className="badge">
                      {item.anchor_status === "located"
                        ? "原文可定位"
                        : item.anchor_status === "page_only"
                          ? "页码级定位"
                          : "来源待处理"}{" "}
                      · 第 {item.page_start} 页
                    </span>
                    <OpenLink
                      href={`/papers/${item.paper_id}?fileId=${item.paper_file_id}&page=${item.page_start}&evidenceId=${item.id}`}
                    >
                      回到原文
                    </OpenLink>
                    <FormDialog
                      title="编辑我的证据解释"
                      trigger={<span className="text-trigger">编辑解释</span>}
                      fields={[
                        {
                          name: "interpretation",
                          label: "我的解释",
                          type: "textarea",
                          required: false,
                          default: item.interpretation,
                        },
                      ]}
                      onSubmit={async (values) => {
                        await write(`/evidence/${item.id}`, "PATCH", {
                          interpretation: values.interpretation,
                          expected_version: item.version,
                        });
                        refresh();
                      }}
                    >
                      <PaginationControls query={evidence} label="可关联证据" />
                    </FormDialog>
                  </div>
                </div>
              ))
            ) : (
              <Empty
                title="让判断回到原始依据"
                text="打开 PDF 并选择原文，将证据关联到这个研究问题。"
              />
            )}
            <PaginationControls query={evidence} label="证据" />
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <FileText size={18} />
                研究假设
              </h2>
              <FormDialog
                title="提出研究假设"
                trigger={<span className="text-trigger">+ 新增假设</span>}
                fields={[
                  {
                    name: "statement",
                    label: "可进一步验证的研究判断",
                    type: "textarea",
                  },
                ]}
                onSubmit={async (values) => {
                  await write(
                    `/threads/${identifier}/hypotheses`,
                    "POST",
                    values,
                  );
                  refresh();
                }}
              />
            </div>
            {hypotheses.error ? (
              <ErrorBox error={hypotheses.error} />
            ) : hypotheses.data?.data.length ? (
              hypotheses.data.data.map((item) => (
                <div className="record-card" key={item.id}>
                  <p>{item.statement}</p>
                  <div className="record-actions">
                    <select
                      aria-label="更新假设判断"
                      value={item.status}
                      onChange={async (event) => {
                        await write(`/hypotheses/${item.id}`, "PATCH", {
                          expected_version: item.version,
                          status: event.target.value,
                        });
                        refresh();
                      }}
                    >
                      {[
                        "proposed",
                        "testing",
                        "supported",
                        "contradicted",
                        "inconclusive",
                      ].map((status) => (
                        <option key={status} value={status}>
                          {statuses[status]}
                        </option>
                      ))}
                    </select>
                    <OpenLink href={`/hypotheses/${item.id}`}>
                      编辑与判断历史
                    </OpenLink>
                    <FormDialog
                      title="关联假设证据"
                      trigger={<span className="text-trigger">关联证据</span>}
                      fields={[
                        {
                          name: "evidence_id",
                          label: "选择同线索证据",
                          type: "select",
                          options: Object.fromEntries(
                            (evidence.data?.data ?? []).map((record) => [
                              record.id,
                              record.quote_text.slice(0, 70),
                            ]),
                          ),
                        },
                        {
                          name: "relation",
                          label: "证据关系",
                          type: "select",
                          options: {
                            support: "支持性线索",
                            challenge: "反面证据",
                            background: "背景信息",
                            uncertain: "暂不确定",
                          },
                        },
                        {
                          name: "explanation",
                          label: "我的关系判断",
                          type: "textarea",
                          required: false,
                        },
                      ]}
                      onSubmit={async (values) => {
                        await write(
                          `/hypotheses/${item.id}/evidence-links`,
                          "POST",
                          { ...values, expected_version: item.version },
                        );
                        refresh();
                      }}
                    />
                  </div>
                </div>
              ))
            ) : (
              <Empty
                title="有什么判断值得验证？"
                text="假设状态由你决定，证据数量不会自动替你下结论。"
              />
            )}
            <PaginationControls query={hypotheses} label="假设" />
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <GitBranch size={18} />
                研究决策
              </h2>
              <DecisionCreator
                workspaceId={user.workspace_id}
                threadId={identifier}
              />
            </div>
            {decisions.error ? (
              <ErrorBox error={decisions.error} />
            ) : decisions.data?.data.length ? (
              decisions.data.data.map((item) => (
                <div className="record-card" key={item.id}>
                  <div className="record-heading">
                    <h3>{item.title}</h3>
                    <span className="badge">v{item.current_revision}</span>
                  </div>
                  <div className="record-actions">
                    <button
                      className="text-button"
                      onClick={async () => {
                        setDetail((await api(`/decisions/${item.id}`)).data);
                      }}
                    >
                      查看决策与依据
                    </button>
                    <TaskDialog
                      workspaceId={user.workspace_id}
                      source={{
                        decisionId: item.id,
                        revision: item.current_revision,
                        projectId: thread.project_id,
                        title: item.title,
                      }}
                    />
                  </div>
                </div>
              ))
            ) : (
              <Empty
                title="记录为什么，而不只是做了什么"
                text="保留方法选择的原因，未来可以回到当时的判断。"
              />
            )}
            <PaginationControls query={decisions} label="决策" />
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <SquareCheck size={18} />
                下一步行动
              </h2>
              <OpenLink href="/tasks">任务管理</OpenLink>
            </div>
            {tasks.data?.data.length ? (
              <TaskRows
                tasks={tasks.data.data}
                workspaceId={user.workspace_id}
              />
            ) : (
              <Empty
                title="把判断转为行动"
                text="从决策卡片创建任务，自动保留它的来源版本。"
              />
            )}
            <PaginationControls query={tasks} label="线索任务" />
          </section>
        </div>
        <aside className="context-panel">
          <h3>一条线索，一个问题</h3>
          <p>
            证据保存原始依据。假设记录你的判断。决策解释选择。任务明确下一步。
          </p>
          <div className="context-rule" />
          <h3>历史不会被覆盖</h3>
          <p>修改研究问题或决策后，原来的内容和依据依然可以查看。</p>
          <OpenLink href="/activity">查看研究日志</OpenLink>
        </aside>
      </div>
      {detail != null && (
        <section className="panel detail-panel">
          <div className="panel-heading">
            <h2>研究记录详情</h2>
            <Button variant="ghost" onClick={() => setDetail(undefined)}>
              关闭
            </Button>
          </div>
          {Array.isArray(detail) ? (
            detail.map((row) => (
              <div className="record-card" key={row.id}>
                <span className="badge">问题 v{row.revision_no}</span>
                <h3>{row.title}</h3>
                <p>{row.question}</p>
                <small>
                  {new Date(row.created_at).toLocaleString("zh-CN")}
                </small>
              </div>
            ))
          ) : (
            <DecisionDetailsPanel
              workspaceId={user.workspace_id}
              detail={detail as DecisionDetail}
              onReload={async () => {
                const value = detail as DecisionDetail;
                setDetail(
                  (
                    await researchRequest<DecisionDetail>(
                      `/decisions/${value.id}`,
                    )
                  ).data,
                );
                refresh();
              }}
            />
          )}
        </section>
      )}
    </>
  );
}

function DecisionDetailsPanel({
  workspaceId,
  detail,
  onReload,
}: {
  workspaceId: string;
  detail: DecisionDetail;
  onReload: () => Promise<void>;
}) {
  const versions = usePagedRows<{ id: string; revision_no: number }>({
    queryKey: scopedKey(workspaceId, "decision-versions", detail.id),
    path: `/decisions/${detail.id}/revisions`,
  });
  const [revision, setRevision] = useState(detail.revision);
  const [error, setError] = useState<unknown>();
  useEffect(() => setRevision(detail.revision), [detail]);
  return (
    <>
      <div className="record-heading">
        <h3>{revision.title_snapshot}</h3>
        <label>
          查看版本{" "}
          <select
            aria-label="查看决策历史版本"
            value={revision.revision_no}
            onChange={async (event) => {
              try {
                setRevision(
                  (
                    await api<DecisionRevision>(
                      `/decisions/${detail.id}/revisions/${event.target.value}`,
                    )
                  ).data,
                );
              } catch (reason) {
                setError(reason);
              }
            }}
          >
            {[
              ...new Set([
                detail.current_revision,
                revision.revision_no,
                ...versions.data.data.map((row) => row.revision_no),
              ]),
            ]
              .sort((a, b) => b - a)
              .map((number) => (
                <option key={number} value={number}>
                  v{number}
                </option>
              ))}
          </select>
        </label>
      </div>
      <PaginationControls query={versions} label="决策历史版本" />
      <div className="decision-reason">
        <strong>当时为什么这样决定</strong>
        <p>{revision.reason}</p>
        <strong>具体方案</strong>
        <p>{revision.content || "未记录方案细节"}</p>
        <strong>当时的依据</strong>
        {revision.evidence.map((item) => (
          <blockquote key={item.evidence_id}>
            {item.quote_snapshot}
            <small>{item.interpretation_snapshot}</small>
          </blockquote>
        ))}
        {revision.hypotheses.map((item) => (
          <p key={item.hypothesis_id}>
            {item.statement_snapshot} · {statuses[item.status_snapshot]}
          </p>
        ))}
        {revision.notes.map((item) => (
          <p key={item.note_id}>
            保存了笔记版本 v{item.note_version} 的内容快照
          </p>
        ))}
      </div>
      {Boolean(error) && <ErrorBox error={error} />}
      <DecisionEditor
        workspaceId={workspaceId}
        item={detail}
        onSaved={onReload}
      />
    </>
  );
}

function ActivityPage({ user, current }: Context) {
  const rows = usePagedRows<Activity>({
    queryKey: scopedKey(user.workspace_id, "activity", current?.id),
    path: `/activity${current ? `?project_id=${current.id}` : ""}`,
  });
  return (
    <>
      <Heading
        eyebrow="RESEARCH TIMELINE"
        title="研究日志"
        text="只记录真实的研究变化，帮助你回到当时的依据。"
      />
      <section className="panel">
        {rows.error ? (
          <ErrorBox error={rows.error} />
        ) : rows.isPending ? (
          <Loading />
        ) : rows.data.data.length ? (
          <ActivityRows items={rows.data.data} />
        ) : (
          <Empty
            title="你的研究历史，从这里开始"
            text="创建线索、记录判断和完成任务都会留下轨迹。"
          />
        )}
        <PaginationControls query={rows} label="研究日志" />
      </section>
    </>
  );
}

function SearchPage({ user }: Context) {
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const rows = useInfiniteQuery({
    queryKey: scopedKey(user.workspace_id, "search", q),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<{ id: string; type: string; title: string }[]>(
        `/search?q=${encodeURIComponent(q)}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    getNextPageParam: (last) => last.meta?.next_cursor ?? undefined,
    enabled: !!q,
  });
  const records = rows.data?.pages.flatMap((page) => page.data) ?? [];
  const labels: Record<string, string> = {
    project: "课题",
    thread: "研究问题",
    paper: "文献",
    note: "笔记",
    task: "任务",
    evidence: "证据",
    hypothesis: "假设",
    decision: "决策",
  };
  return (
    <>
      <Heading
        eyebrow="FIND YOUR RESEARCH"
        title={q ? `搜索：${q}` : "搜索研究资料"}
        text="关键词检索课题、研究问题、文献标题、判断与笔记。不包含 PDF 全文。"
      />
      {rows.error && !rows.data ? (
        <ErrorBox error={rows.error} retry={() => rows.refetch()} />
      ) : (
        <section className="panel">
          {q && rows.isPending ? (
            <Loading />
          ) : records.length ? (
            <>
              {records.map((item) => (
                <Link
                  className="search-result"
                  key={`${item.type}-${item.id}`}
                  href={objectPath(item.type, item.id)}
                >
                  <span className="badge">{labels[item.type]}</span>
                  <h3>{item.title}</h3>
                  <ArrowRight size={17} />
                </Link>
              ))}
              {rows.error && (
                <ErrorBox
                  error={rows.error}
                  retry={() =>
                    rows.isFetchNextPageError
                      ? rows.fetchNextPage({ cancelRefetch: false })
                      : rows.refetch()
                  }
                />
              )}
              {rows.hasNextPage && (
                <Button
                  variant="outline"
                  disabled={rows.isFetching}
                  onClick={() => rows.fetchNextPage({ cancelRefetch: false })}
                >
                  {rows.isFetchingNextPage ? "加载中…" : "加载更多结果"}
                </Button>
              )}
            </>
          ) : (
            <Empty
              title="没有匹配的记录"
              text="换一个关键词，或先保存一些与你的研究有关的资料。"
            />
          )}
        </section>
      )}
    </>
  );
}

export function ResearchPages({
  path,
  ...context
}: Context & { path: string }) {
  const parts = path.split("/").filter(Boolean);
  if (path === "/dashboard") return <DashboardPage {...context} />;
  if (path === "/projects") return <ProjectsPage {...context} />;
  if (parts[0] === "projects" && parts[1])
    return <ProjectPage key={parts[1]} {...context} identifier={parts[1]} />;
  if (parts[0] === "threads" && parts[1])
    return <ThreadPage key={parts[1]} {...context} identifier={parts[1]} />;
  if (parts[0] === "tasks" && parts[1])
    return (
      <TaskDetail key={parts[1]} user={context.user} identifier={parts[1]} />
    );
  if (parts[0] === "tasks") return <TasksPage {...context} />;
  if (parts[0] === "hypotheses" && parts[1])
    return (
      <HypothesisDetailPage
        key={parts[1]}
        user={context.user}
        identifier={parts[1]}
      />
    );
  if (parts[0] === "decisions" && parts[1])
    return (
      <DecisionDetailPage
        key={parts[1]}
        user={context.user}
        identifier={parts[1]}
      />
    );
  if (parts[0] === "evidence" && parts[1])
    return (
      <EvidenceDetailPage
        key={parts[1]}
        user={context.user}
        identifier={parts[1]}
      />
    );
  if (path === "/activity") return <ActivityPage {...context} />;
  if (path === "/search") return <SearchPage {...context} />;
  if (path === "/onboarding") return <OnboardingPage {...context} />;
  if (path === "/library") return <LibraryPage {...context} />;
  if (parts[0] === "papers" && parts[1])
    return <PdfReader key={parts[1]} {...context} identifier={parts[1]} />;
  if (path === "/notes") return <NotesPage {...context} />;
  if (parts[0] === "notes" && parts[1])
    return <NotePage key={parts[1]} {...context} identifier={parts[1]} />;
  if (path === "/profile/research") return <ProfilePage {...context} />;
  if (path === "/settings/data") return <DataSettings user={context.user} />;
  return (
    <>
      <Heading
        eyebrow="RESEARCHOS DEVELOPMENT"
        title={
          parts[0] === "library"
            ? "文献库"
            : parts[0] === "notes"
              ? "科研笔记"
              : "科研资料与设置"
        }
        text="这个模块正在接入真实业务服务，尚未通过功能验收。"
      />
      <Empty
        title="模块开发进行中"
        text="PDF 阅读、笔记编辑、科研画像与导出属于当前开发范围，会继续接入，不用示例数据代替。"
      />
    </>
  );
}
