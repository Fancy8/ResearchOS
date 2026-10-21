"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { taskRequest } from "@/lib/task-request";
import { scopedKey } from "@/lib/query-client";
import { statuses, type Task } from "@/lib/types";
import { ErrorBox } from "./common";
import { Button } from "./ui/button";

export function useTaskStatus(workspaceId: string, source?: Task) {
  const cache = useQueryClient();
  const [latest, setLatest] = useState<Task>();
  const [error, setError] = useState<unknown>();
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  const busy = useRef(false);
  const attempt = useRef<{
    id: string;
    expected_version: number;
    status: string;
  } | null>(null);
  const task =
    source && latest?.id === source.id && latest.version > source.version
      ? latest
      : source;
  function remember(value: Task) {
    setLatest(value);
    cache.setQueryData<{ data: Task }>(
      scopedKey(workspaceId, "task", value.id),
      (previous) =>
        previous && previous.data.version > value.version
          ? previous
          : { data: value },
    );
  }
  async function run(retry = false) {
    if (!task || busy.current) return;
    if (!retry || !attempt.current)
      attempt.current = {
        id: task.id,
        expected_version: task.version,
        status: task.status === "done" ? "todo" : "done",
      };
    const request = attempt.current;
    busy.current = true;
    setPending(true);
    setError(undefined);
    setNotice("");
    try {
      const saved = await taskRequest(`/tasks/${request.id}`, "PATCH", {
        expected_version: request.expected_version,
        status: request.status,
      });
      remember(saved.data);
      attempt.current = null;
      setConflict(false);
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    } catch (reason) {
      setConflict(
        reason instanceof ApiError && reason.code === "VERSION_CONFLICT",
      );
      setError(reason);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  async function reload() {
    if (!task || busy.current) return;
    busy.current = true;
    setPending(true);
    try {
      const value = (await taskRequest(`/tasks/${task.id}`)).data;
      const confirmed = attempt.current?.status === value.status;
      remember(value);
      attempt.current = null;
      setError(undefined);
      setConflict(false);
      setNotice(
        confirmed
          ? "已从服务器确认任务状态。"
          : "已读取最新状态，请确认后再操作。",
      );
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    } catch (reason) {
      setError(reason);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  return {
    task,
    error,
    conflict,
    pending,
    notice,
    toggle: () => run(),
    retry: () => run(true),
    reload,
  };
}

export function TaskStatusFeedback({
  action,
}: {
  action: ReturnType<typeof useTaskStatus>;
}) {
  return (
    <>
      {Boolean(action.error) && (
        <div className="task-action-feedback">
          <ErrorBox error={action.error} />
          <p>
            {action.conflict
              ? "任务版本已变化。请先读取最新状态，再决定是否操作。"
              : "状态尚未确认。可以重试原请求，或读取最新状态。"}
          </p>
          <div className="record-actions">
            {!action.conflict && (
              <Button
                type="button"
                variant="outline"
                disabled={action.pending}
                onClick={action.retry}
              >
                重试原请求
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={action.pending}
              onClick={action.reload}
            >
              读取最新状态
            </Button>
          </div>
        </div>
      )}
      {action.notice && (
        <p className="muted" role="status">
          {action.notice}
        </p>
      )}
    </>
  );
}

function TaskRow({
  source,
  workspaceId,
}: {
  source: Task;
  workspaceId: string;
}) {
  const action = useTaskStatus(workspaceId, source);
  const task = action.task!;
  return (
    <article className="task-record" aria-label={task.title}>
      <div className="task-row">
        <button
          type="button"
          className={`task-check ${task.status === "done" ? "checked" : ""}`}
          aria-label={`${task.status === "done" ? "重开" : "完成"} ${task.title}`}
          aria-busy={action.pending}
          disabled={action.pending || Boolean(action.error)}
          onClick={action.toggle}
        >
          {task.status === "done" && <Check size={15} />}
        </button>
        <div>
          <strong>
            <Link href={`/tasks/${task.id}`}>{task.title}</Link>
          </strong>
          <span>
            {task.decision_id
              ? `来自决策 v${task.source_revision_no}`
              : "自主研究行动"}
            {task.due_date && ` · ${task.due_date}`}
          </span>
        </div>
        <span className={`badge status-${task.status}`}>
          {statuses[task.status]}
        </span>
      </div>
      <TaskStatusFeedback action={action} />
    </article>
  );
}

export function TaskRows({
  tasks,
  workspaceId,
}: {
  tasks: Task[];
  workspaceId: string;
}) {
  return (
    <div className="task-rows">
      {tasks.map((task) => (
        <TaskRow key={task.id} source={task} workspaceId={workspaceId} />
      ))}
    </div>
  );
}
