"use client";
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { DeletionJob } from "./deletion-control";
import { Button } from "./ui/button";
import { ErrorBox, Loading } from "./common";

export function DeletionStatus() {
  const id = useSearchParams().get("id") ?? "";
  const [receipt, setReceipt] = useState(() =>
    typeof window === "undefined"
      ? ""
      : (sessionStorage.getItem(`researchos.deletion.${id}`) ?? ""),
  );
  const job = useQuery({
    queryKey: ["deletion-status", id, receipt],
    queryFn: () =>
      api<DeletionJob>(`/deletions/${id}`, {
        headers: { "X-Deletion-Receipt": receipt },
      }),
    enabled: !!id && !!receipt,
    retry: false,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.data.status ?? "")
        ? 2000
        : false,
  });
  return (
    <main className="deletion-status panel">
      <div className="eyebrow">RESEARCHOS · DATA CONTROL</div>
      <h1>删除处理进度</h1>
      <p>回执用于在会话撤销后查看清理进度。请独立保存回执，不要向他人分享。</p>
      <label>
        删除回执
        <input
          value={receipt}
          onChange={(event) => {
            setReceipt(event.target.value);
            sessionStorage.setItem(
              `researchos.deletion.${id}`,
              event.target.value,
            );
          }}
        />
      </label>
      {receipt && (
        <Button
          variant="outline"
          onClick={() => {
            const link = document.createElement("a");
            const url = URL.createObjectURL(
              new Blob([JSON.stringify({ id, receipt }, null, 2)], {
                type: "application/json",
              }),
            );
            link.href = url;
            link.download = `ResearchOS-deletion-${id}.json`;
            link.click();
            URL.revokeObjectURL(url);
          }}
        >
          保存删除回执
        </Button>
      )}
      {job.isFetching && !job.data ? (
        <Loading />
      ) : job.error ? (
        <ErrorBox error={job.error} />
      ) : (
        job.data && (
          <>
            <h2>
              {
                {
                  queued: "等待清理服务",
                  running: "正在清理在线资料",
                  succeeded: "在线删除已完成",
                  failed: "清理失败，需恢复清理服务后重试",
                }[job.data.data.status]
              }
            </h2>
            {job.data.data.online_finished_at && (
              <p>
                在线清理完成：
                {new Date(job.data.data.online_finished_at).toLocaleString(
                  "zh-CN",
                )}
              </p>
            )}
            <p>{job.data.data.backup_status}</p>
            {job.data.data.error_code && (
              <p>处理状态：{job.data.data.error_code}</p>
            )}
            {job.data.data.scope === "file" && (
              <Button asChild variant="outline">
                <Link href="/library">返回文献库</Link>
              </Button>
            )}
          </>
        )
      )}
      <p>
        <Link href="/login">前往登录页</Link>
      </p>
    </main>
  );
}
