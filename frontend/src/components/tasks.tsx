"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { usePagedRows, type PageState } from "@/lib/pagination";
import { scopedKey } from "@/lib/query-client";
import { statuses, type Task, type Project, type User } from "@/lib/types";
import { Empty, ErrorBox, Heading, Loading } from "./common";
import { TaskRows } from "./task-actions";
import { TaskDialog } from "./task-dialog";
import { PaginationControls } from "./pagination-controls";
import { Button } from "./ui/button";

function validDate(value: string) {
  if (!value) return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

export function TasksPage({
  user,
  current,
  projects,
  projectPaging,
}: {
  user: User;
  current?: Project;
  projects: Project[];
  projectPaging?: PageState;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const status = params.get("status") ?? "";
  const priority = params.get("priority") ?? "";
  const from = params.get("due_from") ?? "";
  const to = params.get("due_to") ?? "";
  const scope = params.get("scope") ?? "current";
  const valid =
    ["", "todo", "doing", "done", "blocked"].includes(status) &&
    ["", "low", "medium", "high"].includes(priority) &&
    validDate(from) &&
    validDate(to) &&
    (!from || !to || from <= to) &&
    ["all", "current"].includes(scope);
  const query = new URLSearchParams();
  if (scope === "current" && current) query.set("project_id", current.id);
  for (const [key, value] of [
    ["status", status],
    ["priority", priority],
    ["due_from", from],
    ["due_to", to],
  ])
    if (value) query.set(key, value);
  const rows = usePagedRows<Task>({
    queryKey: scopedKey(
      user.workspace_id,
      "all-tasks",
      scope === "all" ? "all" : current?.id,
    ),
    path: `/tasks?${query}`,
    enabled: valid && (scope === "all" || Boolean(current)),
  });
  const filtered = Boolean(status || priority || from || to);
  function apply(form: HTMLFormElement) {
    const values = new FormData(form);
    const next = new URLSearchParams();
    for (const key of ["status", "priority", "due_from", "due_to", "scope"]) {
      const value = String(values.get(key) ?? "");
      if (value && !(key === "scope" && value === "current"))
        next.set(key, value);
    }
    router.push(`/tasks${next.size ? `?${next}` : ""}`, { scroll: false });
  }
  return (
    <>
      <Heading
        eyebrow="NEXT RESEARCH ACTIONS"
        title="下一步行动"
        text="任务可以独立创建，也可以保留它来自哪一次研究决策。"
        action={
          <TaskDialog
            workspaceId={user.workspace_id}
            current={current}
            projects={projects}
            projectPaging={projectPaging}
          />
        }
      />
      <section className="panel" aria-label="任务筛选">
        <form
          key={params.toString()}
          className="task-filter-form"
          onSubmit={(event) => {
            event.preventDefault();
            apply(event.currentTarget);
          }}
        >
          <div className="field">
            <label htmlFor="task-scope">课题范围</label>
            <select id="task-scope" name="scope" defaultValue={scope}>
              <option value="current">当前课题</option>
              <option value="all">所有课题</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="task-status-filter">筛选任务状态</label>
            <select id="task-status-filter" name="status" defaultValue={status}>
              <option value="">全部状态</option>
              {["todo", "doing", "done", "blocked"].map((value) => (
                <option key={value} value={value}>
                  {statuses[value]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="task-priority-filter">筛选优先级</label>
            <select
              id="task-priority-filter"
              name="priority"
              defaultValue={priority}
            >
              <option value="">全部优先级</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="task-due-from">截止日期从</label>
            <input
              id="task-due-from"
              name="due_from"
              type="date"
              defaultValue={from}
            />
          </div>
          <div className="field">
            <label htmlFor="task-due-to">截止日期至</label>
            <input
              id="task-due-to"
              name="due_to"
              type="date"
              defaultValue={to}
            />
          </div>
          <div className="task-filter-buttons">
            <Button type="submit">应用筛选</Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => router.push("/tasks", { scroll: false })}
            >
              重置筛选
            </Button>
          </div>
        </form>
      </section>
      <section
        className="panel"
        aria-label="任务列表"
        aria-busy={rows.isFetching}
      >
        {!valid ? (
          <ErrorBox
            error={
              new Error(
                "筛选条件无效，或截止日期起始值晚于结束值。请修改条件或重置筛选。",
              )
            }
          />
        ) : scope === "current" && !current ? (
          <Empty
            title="先选择研究课题"
            text="创建课题后添加任务，也可以切换到所有课题查看已有任务。"
            action={<Link href="/projects">前往课题管理</Link>}
          />
        ) : rows.error ? (
          <ErrorBox error={rows.error} retry={() => rows.refetch()} />
        ) : rows.isPending ? (
          <Loading />
        ) : rows.data.data.length ? (
          <TaskRows tasks={rows.data.data} workspaceId={user.workspace_id} />
        ) : (
          <Empty
            title={filtered ? "没有符合筛选条件的任务" : "清楚知道下一步"}
            text={
              filtered
                ? "调整状态、优先级或截止日期，或者重置筛选。"
                : "创建一个具体、可执行的研究任务。"
            }
          />
        )}
        {Boolean(rows.pageError) && (
          <p className="muted">列表尚未重新加载，当前保留已读取的记录。</p>
        )}
        {valid && (scope === "all" || current) && !rows.error && (
          <PaginationControls query={rows} label="任务" />
        )}
      </section>
    </>
  );
}
