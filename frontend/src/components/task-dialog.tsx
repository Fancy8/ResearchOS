"use client";
import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { taskRequest } from "@/lib/task-request";
import { SAFE_REPLAY_AGE_MS } from "@/lib/research-request";
import { scopedKey } from "@/lib/query-client";
import { statuses, type Task, type Project } from "@/lib/types";
import type { PageState } from "@/lib/pagination";
import { ErrorBox } from "./common";
import { PaginationControls } from "./pagination-controls";
import { Button } from "./ui/button";

type Values = {
  title: string;
  description: string;
  status: string;
  priority: string;
  due_date: string;
  project_id: string;
};
type DecisionSource = {
  decisionId: string;
  revision: number;
  projectId: string;
  title: string;
};
function initial(task?: Task, project?: Project): Values {
  return {
    title: task?.title ?? "",
    description: task?.description ?? "",
    status: task?.status ?? "todo",
    priority: task?.priority ?? "medium",
    due_date: task?.due_date ?? "",
    project_id: task?.project_id ?? project?.id ?? "",
  };
}

export function TaskDialog({
  workspaceId,
  task,
  current,
  projects = [],
  projectPaging,
  source,
}: {
  workspaceId: string;
  task?: Task;
  current?: Project;
  projects?: Project[];
  projectPaging?: PageState;
  source?: DecisionSource;
}) {
  const cache = useQueryClient();
  const modal = useRef<HTMLDialogElement>(null);
  const label = useId();
  const [values, setValues] = useState<Values>(() => initial(task, current));
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const expectedVersion = useRef(task?.version);
  const request = useRef<{
    key: string;
    values: Values;
    body: object;
    uncertain: boolean;
    path: string;
    createdAt: number;
  } | null>(null);
  const [remote, setRemote] = useState<Task>();
  const [notice, setNotice] = useState("");
  const [openingProject, setOpeningProject] = useState(current);
  const sourceSnapshot = useRef(source);
  const options = [
    ...new Map(
      [
        ...(openingProject ? [openingProject] : []),
        ...(current ? [current] : []),
        ...projects,
      ].map((item) => [item.id, item]),
    ).values(),
  ].filter((item) => item.status !== "archived");
  const title = task
    ? "编辑科研任务"
    : source
      ? "从决策创建下一步任务"
      : "创建科研任务";
  function open() {
    if (task) {
      setValues(initial(task));
      expectedVersion.current = task.version;
    } else if (!request.current) {
      setValues({
        ...initial(undefined, current),
        ...(source ? { project_id: source.projectId } : {}),
      });
      setOpeningProject(current);
      sourceSnapshot.current = source;
    }
    setError(undefined);
    setRemote(undefined);
    setNotice("");
    modal.current?.showModal();
  }
  async function submit(replay = false) {
    if (busy.current) return;
    // Server idempotency records expire after one day. Leave margin and never
    // replay an uncertain create after that protection may have elapsed.
    if (
      !task &&
      request.current?.uncertain &&
      Date.now() - request.current.createdAt >= SAFE_REPLAY_AGE_MS
    ) {
      setError(
        new Error(
          "原请求已超过可安全重试时限。请先到任务列表核对创建结果，再决定后续操作。",
        ),
      );
      return;
    }
    const input = replay && request.current ? request.current.values : values;
    const body = {
      title: input.title.trim(),
      description: input.description,
      priority: input.priority,
      due_date: input.due_date || null,
      ...(task ? { status: input.status } : { project_id: input.project_id }),
    };
    if (
      !task &&
      request.current?.uncertain &&
      JSON.stringify(request.current.body) !== JSON.stringify(body)
    ) {
      setError(
        new Error(
          "上次创建结果尚未确认，请先重试原请求。当前输入仍保留在表单中。",
        ),
      );
      return;
    }
    if (!task && !request.current?.uncertain)
      request.current = {
        key: request.current?.key ?? crypto.randomUUID(),
        body,
        values: { ...input },
        uncertain: false,
        path: sourceSnapshot.current
          ? `/decisions/${sourceSnapshot.current.decisionId}/revisions/${sourceSnapshot.current.revision}/tasks`
          : "/tasks",
        createdAt: Date.now(),
      };
    if (replay) setValues(input);
    busy.current = true;
    setPending(true);
    setError(undefined);
    setNotice("");
    try {
      const saved = task
        ? await taskRequest(`/tasks/${task.id}`, "PATCH", {
            ...body,
            expected_version: expectedVersion.current,
          })
        : await taskRequest(
            request.current!.path,
            "POST",
            request.current!.body,
            request.current!.key,
          );
      cache.setQueryData<{ data: Task }>(
        scopedKey(workspaceId, "task", saved.data.id),
        (previous) =>
          previous && previous.data.version > saved.data.version
            ? previous
            : saved,
      );
      request.current = null;
      modal.current?.close();
      if (!task) setValues(initial(undefined, current));
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    } catch (reason) {
      if (
        !task &&
        request.current &&
        !(reason instanceof ApiError && [400, 422].includes(reason.status))
      )
        request.current.uncertain = true;
      if (
        task &&
        reason instanceof ApiError &&
        reason.code === "VERSION_CONFLICT"
      ) {
        try {
          setRemote((await taskRequest(`/tasks/${task.id}`)).data);
        } catch {
          setNotice(
            "服务器版本暂时无法读取。可再次保存以重新核对，当前输入已保留。",
          );
        }
      }
      setError(reason);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  function field(name: keyof Values, value: string) {
    setValues((previous) => ({ ...previous, [name]: value }));
  }
  return (
    <>
      <button
        type="button"
        className="dialog-trigger"
        disabled={pending}
        onClick={open}
      >
        <span
          className={
            task
              ? "secondary-trigger"
              : source
                ? "text-trigger"
                : "primary-trigger"
          }
        >
          {task ? "编辑任务" : source ? "创建行动 →" : "新建任务"}
        </span>
      </button>
      <dialog
        ref={modal}
        className="form-dialog"
        aria-labelledby={label}
        onClose={() =>
          void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] })
        }
      >
        <div className="dialog-heading">
          <h2 id={label}>{title}</h2>
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
          <fieldset
            className="task-fields"
            disabled={pending || (!task && Boolean(request.current?.uncertain))}
          >
            <div className="field">
              <label htmlFor={`${label}-title`}>
                {source ? "具体行动 *" : "任务名称 *"}
              </label>
              <input
                id={`${label}-title`}
                value={values.title}
                maxLength={250}
                required
                onChange={(event) => field("title", event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`${label}-description`}>任务说明</label>
              <textarea
                id={`${label}-description`}
                value={values.description}
                maxLength={20000}
                rows={4}
                onChange={(event) => field("description", event.target.value)}
              />
            </div>
            {!task && !source && (
              <div className="field">
                <label htmlFor={`${label}-project`}>所属课题 *</label>
                <select
                  id={`${label}-project`}
                  value={values.project_id}
                  required
                  onChange={(event) => field("project_id", event.target.value)}
                >
                  <option value="">选择课题</option>
                  {options.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {task && (
              <div className="field">
                <label htmlFor={`${label}-status`}>任务状态</label>
                <select
                  id={`${label}-status`}
                  value={values.status}
                  onChange={(event) => field("status", event.target.value)}
                >
                  {["todo", "doing", "done", "blocked"].map((value) => (
                    <option key={value} value={value}>
                      {statuses[value]}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="field">
              <label htmlFor={`${label}-priority`}>优先级</label>
              <select
                id={`${label}-priority`}
                value={values.priority}
                onChange={(event) => field("priority", event.target.value)}
              >
                <option value="low">低</option>
                <option value="medium">中</option>
                <option value="high">高</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${label}-due`}>截止日期</label>
              <input
                id={`${label}-due`}
                type="date"
                value={values.due_date}
                onChange={(event) => field("due_date", event.target.value)}
              />
            </div>
          </fieldset>
          {sourceSnapshot.current && (
            <p className="muted">
              来自决策 v{sourceSnapshot.current.revision}：
              {sourceSnapshot.current.title}。保存与重试均保留这个修订。
            </p>
          )}
          {Boolean(error) && <ErrorBox error={error} />}
          {notice && <p role="status">{notice}</p>}
          {!task && request.current?.uncertain && (
            <div className="task-server-conflict">
              <p>
                上次创建结果尚未确认，表单已保留。请先重试原请求确认结果，再编辑任务。
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
          {remote && (
            <section
              className="task-server-conflict"
              aria-label="服务器任务版本"
            >
              <strong>服务器版本 v{remote.version}</strong>
              <p>{remote.title}</p>
              <p className="task-conflict-description">
                {remote.description || "无任务说明"}
              </p>
              <p>
                {statuses[remote.status]} · 优先级{" "}
                {{ low: "低", medium: "中", high: "高" }[remote.priority]} ·{" "}
                {remote.due_date ?? "未设置截止日期"}
              </p>
              <p>
                当前输入仍保留。请对照服务器内容，手动修改后再确认继续编辑。
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  expectedVersion.current = remote.version;
                  setRemote(undefined);
                  setNotice(
                    `已确认服务器 v${remote.version}，下次保存提交当前表单输入。`,
                  );
                }}
              >
                已对照，保留输入继续编辑
              </Button>
            </section>
          )}
          {!task && projectPaging && (
            <PaginationControls query={projectPaging} label="任务所属课题" />
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
              disabled={
                pending ||
                Boolean(remote) ||
                (!task && Boolean(request.current?.uncertain))
              }
            >
              {pending ? "保存中…" : "保存"}
            </Button>
          </div>
        </form>
      </dialog>
    </>
  );
}
