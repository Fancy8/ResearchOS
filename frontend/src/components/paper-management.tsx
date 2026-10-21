"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write } from "@/lib/api";
import { usePagedRows } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";
import { scopedKey } from "@/lib/query-client";
import type { User } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";
import { DeletionControl } from "./deletion-control";
import { ParseRetry } from "./parse-retry";
import type { Paper } from "./library";

type Version = {
  id: string;
  version_no: number;
  original_filename: string;
  upload_status: string;
  parse_status: string;
  availability_status: string;
  is_current: boolean;
};
export function PaperManagement({
  user,
  identifier,
}: {
  user: User;
  identifier: string;
}) {
  const cache = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState(false);
  const files = usePagedRows<Version>({
    queryKey: scopedKey(user.workspace_id, "paper-versions", identifier),
    path: `/papers/${identifier}/files`,
    refetchInterval: (rows) =>
      rows.some((file) =>
        ["pending", "queued", "processing"].includes(file.parse_status),
      )
        ? 2000
        : false,
  });
  const currentFile = files.data.data.find((file) => file.is_current);
  // Upload completion only queues verification/parsing. Its first refresh may
  // still return the previous current file; follow the worker's later commit.
  useEffect(() => {
    if (!currentFile) return;
    void cache.invalidateQueries({
      queryKey: scopedKey(user.workspace_id, "paper-file", identifier),
    });
  }, [
    cache,
    user.workspace_id,
    identifier,
    currentFile?.id,
    currentFile?.upload_status,
    currentFile?.parse_status,
    currentFile?.availability_status,
  ]);
  const paper = useQuery({
    queryKey: scopedKey(user.workspace_id, "paper", identifier),
    queryFn: () => api<Paper & { doi: string | null }>(`/papers/${identifier}`),
  });
  async function refresh() {
    await cache.invalidateQueries({
      queryKey: ["workspace", user.workspace_id],
    });
  }
  return (
    <details className="panel paper-management">
      <summary>文献元数据与文件版本</summary>
      {files.error && <ErrorBox error={files.error} />}
      {paper.data && (
        <>
          <p>
            DOI：{paper.data.data.doi ?? "未设置"} ·
            文献版本更换不会改变旧证据的来源。
          </p>
          {!editing ? (
            <Button variant="outline" onClick={() => setEditing(true)}>
              编辑文献元数据
            </Button>
          ) : (
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                const form = new FormData(event.currentTarget);
                setPending(true);
                setError(undefined);
                try {
                  await write(`/papers/${identifier}`, "PATCH", {
                    expected_version: paper.data.data.version,
                    title: form.get("title"),
                    authors: String(form.get("authors"))
                      .split(";")
                      .map((value) => value.trim())
                      .filter(Boolean),
                    publication_year: form.get("year")
                      ? Number(form.get("year"))
                      : null,
                    doi: form.get("doi") || null,
                  });
                  setEditing(false);
                  await refresh();
                } catch (reason) {
                  setError(reason);
                } finally {
                  setPending(false);
                }
              }}
            >
              <label>
                文献标题
                <input
                  name="title"
                  defaultValue={paper.data.data.title}
                  required
                />
              </label>
              <label>
                作者（分号分隔）
                <input
                  name="authors"
                  defaultValue={paper.data.data.authors.join("; ")}
                />
              </label>
              <label>
                出版年份
                <input
                  name="year"
                  type="number"
                  min="1500"
                  max="2200"
                  defaultValue={paper.data.data.publication_year ?? ""}
                />
              </label>
              <label>
                DOI
                <input name="doi" defaultValue={paper.data.data.doi ?? ""} />
              </label>
              <Button disabled={pending} type="submit">
                保存元数据
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setEditing(false)}
              >
                取消
              </Button>
            </form>
          )}
        </>
      )}
      {files.data?.data.map((file) => (
        <div className="file-version" key={file.id}>
          <p>
            <strong>
              v{file.version_no}
              {file.is_current && " · 当前版本"}
            </strong>{" "}
            · {file.original_filename} ·{" "}
            {
              {
                ready: "解析完成",
                failed: "解析失败",
                pending: "等待上传",
                queued: "等待解析",
                processing: "解析中",
              }[file.parse_status]
            }
            {file.availability_status !== "available" && " · 原文件不可用"}
          </p>
          {file.upload_status === "uploaded" &&
            file.availability_status === "available" && (
              <>
                <Button asChild variant="outline">
                  <Link href={`/papers/${identifier}?fileId=${file.id}`}>
                    阅读此版本
                  </Link>
                </Button>
                {!file.is_current && (
                  <Button
                    variant="outline"
                    disabled={pending}
                    onClick={async () => {
                      setPending(true);
                      setError(undefined);
                      try {
                        await write(
                          `/papers/${identifier}/files/${file.id}/set-current`,
                          "POST",
                          {},
                        );
                        await refresh();
                      } catch (reason) {
                        setError(reason);
                      } finally {
                        setPending(false);
                      }
                    }}
                  >
                    设为当前版本
                  </Button>
                )}
              </>
            )}
          <ParseRetry
            workspaceId={user.workspace_id}
            paperId={identifier}
            fileId={file.id}
            status={file.parse_status}
            available={file.availability_status === "available"}
          />
          {file.availability_status === "available" && (
            <DeletionControl
              scope="file"
              targetId={file.id}
              workspaceId={user.workspace_id}
            />
          )}
        </div>
      ))}
      {Boolean(error) && <ErrorBox error={error} />}
      <PaginationControls query={files} label="文件版本" />
    </details>
  );
}
