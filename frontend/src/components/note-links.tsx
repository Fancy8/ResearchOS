"use client";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { write } from "@/lib/api";
import { usePagedRows, type PageState } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";
import { scopedKey } from "@/lib/query-client";
import { objectPath } from "@/lib/navigation";
import type { User, Project, Thread } from "@/lib/types";
import { ErrorBox, FormDialog } from "./common";
import { Button } from "./ui/button";

type Target = { id: string; title: string };
const labels = {
  project: "课题",
  thread: "研究线索",
  paper: "文献",
  evidence: "证据",
};
type Kind = keyof typeof labels;

function LinkedGroup({
  user,
  noteId,
  kind,
  refresh,
}: {
  user: User;
  noteId: string;
  kind: Kind;
  refresh: () => Promise<unknown>;
}) {
  const [error, setError] = useState<unknown>();
  const rows = usePagedRows<Target>({
    queryKey: scopedKey(user.workspace_id, "note-links", noteId, kind),
    path: `/notes/${noteId}/links?kind=${kind}`,
  });
  return (
    <div className="linked-assets">
      <h3>{labels[kind]}</h3>
      {Boolean(error || rows.error) && <ErrorBox error={error || rows.error} />}
      {rows.data.data.map((row) => (
        <div className="linked-asset" key={row.id}>
          <Link href={objectPath(kind, row.id)}>{row.title.slice(0, 100)}</Link>
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              try {
                setError(undefined);
                await write(
                  `/notes/${noteId}/${kind}-links/${row.id}`,
                  "DELETE",
                  {},
                );
                await refresh();
              } catch (reason) {
                setError(reason);
              }
            }}
          >
            移除关联
          </Button>
        </div>
      ))}
      <PaginationControls query={rows} label={`已关联${labels[kind]}`} />
    </div>
  );
}
export function NoteLinks({ user, noteId }: { user: User; noteId: string }) {
  const cache = useQueryClient();
  const [projectId, setProjectId] = useState("");
  const [threadId, setThreadId] = useState("");
  const projects = usePagedRows<Project>({
    queryKey: scopedKey(user.workspace_id, "projects"),
    path: "/projects",
  });
  const threads = usePagedRows<Thread>({
    queryKey: scopedKey(user.workspace_id, "note-link-threads", projectId),
    path: `/projects/${projectId}/threads`,
    enabled: !!projectId,
  });
  const papers = usePagedRows<Target>({
    queryKey: scopedKey(user.workspace_id, "papers"),
    path: "/papers",
  });
  const evidence = usePagedRows<{ id: string; quote_text: string }>({
    queryKey: scopedKey(user.workspace_id, "note-link-evidence", threadId),
    path: `/threads/${threadId}/evidence`,
    enabled: !!threadId,
  });
  const pickers: Record<string, PageState> = {
    project: projects,
    thread: threads,
    paper: papers,
    evidence,
  };
  const refresh = () =>
    cache.invalidateQueries({ queryKey: ["workspace", user.workspace_id] });
  return (
    <section className="panel note-associations">
      <div className="panel-heading">
        <h2>这份笔记关联的研究资料</h2>
        <span className="muted">同一份笔记可以被多个课题使用</span>
      </div>
      {(Object.keys(labels) as Kind[]).map((kind) => (
        <LinkedGroup
          key={kind}
          user={user}
          noteId={noteId}
          kind={kind}
          refresh={refresh}
        />
      ))}
      <div className="relation-context">
        <label>
          选择关联上下文
          <select
            aria-label="笔记关联课题上下文"
            value={projectId}
            onChange={(event) => {
              setProjectId(event.target.value);
              setThreadId("");
            }}
          >
            <option value="">选择课题以查找研究线索</option>
            {projects.data?.data.map((project) => (
              <option key={project.id} value={project.id}>
                {project.title}
              </option>
            ))}
          </select>
        </label>
        {projectId && (
          <label>
            研究线索
            <select
              aria-label="笔记关联线索上下文"
              value={threadId}
              onChange={(event) => setThreadId(event.target.value)}
            >
              <option value="">选择线索以查找证据</option>
              {threads.data?.data.map((thread) => (
                <option key={thread.id} value={thread.id}>
                  {thread.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <PaginationControls query={projects} label="关联上下文课题" />
      {projectId && (
        <PaginationControls query={threads} label="关联上下文线索" />
      )}
      <div className="record-actions">
        {Object.entries({
          project: Object.fromEntries(
            (projects.data?.data ?? []).map((row) => [row.id, row.title]),
          ),
          thread: Object.fromEntries(
            (threads.data?.data ?? []).map((row) => [row.id, row.title]),
          ),
          paper: Object.fromEntries(
            (papers.data?.data ?? []).map((row) => [row.id, row.title]),
          ),
          evidence: Object.fromEntries(
            (evidence.data?.data ?? []).map((row) => [
              row.id,
              row.quote_text.slice(0, 100),
            ]),
          ),
        }).map(([key, options]) => {
          const kind = key as Kind;
          return (
            <FormDialog
              key={kind}
              title={`关联${labels[kind]}`}
              trigger={
                <span className="secondary-trigger">关联{labels[kind]}</span>
              }
              fields={[
                {
                  name: "id",
                  label: `选择${labels[kind]}`,
                  type: "select",
                  options,
                },
              ]}
              onSubmit={async (values) => {
                await write(`/notes/${noteId}/${kind}-links`, "POST", values);
                refresh();
              }}
            >
              <PaginationControls
                query={pickers[kind]}
                label={`可关联${labels[kind]}`}
              />
            </FormDialog>
          );
        })}
      </div>
    </section>
  );
}
