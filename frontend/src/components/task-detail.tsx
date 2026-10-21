"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import { statuses, type Task, type User } from "@/lib/types";
import { ErrorBox, Heading, Loading } from "./common";
import { Button } from "./ui/button";
import { TaskDialog } from "./task-dialog";
import { useTaskStatus, TaskStatusFeedback } from "./task-actions";

export function TaskDetail({
  user,
  identifier,
}: {
  user: User;
  identifier: string;
}) {
  const result = useQuery({
    queryKey: scopedKey(user.workspace_id, "task", identifier),
    queryFn: () => api<Task>(`/tasks/${identifier}`),
  });
  const action = useTaskStatus(user.workspace_id, result.data?.data);
  if (result.isPending) return <Loading />;
  if (result.error && !result.data)
    return <ErrorBox error={result.error} retry={() => result.refetch()} />;
  const task = action.task!;
  return (
    <>
      <Link className="breadcrumb" href="/tasks">
        下一步行动 / 任务详情
      </Link>
      <Heading
        eyebrow="RESEARCH ACTION"
        title={task.title}
        text={task.description || "记录具体行动，保留它从哪里产生。"}
        action={<TaskDialog workspaceId={user.workspace_id} task={task} />}
      />
      <TaskStatusFeedback action={action} />
      {Boolean(result.error) && (
        <ErrorBox error={result.error} retry={() => result.refetch()} />
      )}
      <section className="panel">
        <div className="task-detail-facts">
          <div>
            <span>当前状态</span>
            <strong>{statuses[task.status]}</strong>
          </div>
          <div>
            <span>优先级</span>
            <strong>
              {{ low: "低", medium: "中", high: "高" }[task.priority]}
            </strong>
          </div>
          <div>
            <span>截止日期</span>
            <strong>{task.due_date ?? "未设置"}</strong>
          </div>
        </div>
        <div className="record-actions">
          <Button
            disabled={action.pending || Boolean(action.error)}
            aria-busy={action.pending}
            onClick={action.toggle}
          >
            {action.pending
              ? "正在保存…"
              : task.status === "done"
                ? "重新设为待办"
                : "完成任务"}
          </Button>
          <Button asChild variant="outline">
            <Link href={`/projects/${task.project_id}`}>所属课题</Link>
          </Button>
          {task.thread_id && (
            <Button asChild variant="outline">
              <Link href={`/threads/${task.thread_id}`}>相关研究线索</Link>
            </Button>
          )}
          {task.decision_id && (
            <Button asChild variant="outline">
              <Link
                href={`/decisions/${task.decision_id}?revision=${task.source_revision_no}`}
              >
                查看任务产生时的决策 v{task.source_revision_no}
              </Link>
            </Button>
          )}
        </div>
      </section>
    </>
  );
}
