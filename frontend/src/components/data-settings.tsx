"use client";
import { Archive, ShieldCheck } from "lucide-react";
import { scopedKey } from "@/lib/query-client";
import type { User } from "@/lib/types";
import { Empty, ErrorBox, Heading, Loading } from "./common";
import { DeletionControl } from "./deletion-control";
import { usePagedRows } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";

import { ExportControl } from "./export-control";
import { ExportDownload } from "./export-download";
import {
  exportExpired,
  exportFailure,
  exportNames,
  type ExportJob,
} from "@/lib/export-recovery";

export function DataSettings({ user }: { user: User }) {
  const jobs = usePagedRows<ExportJob>({
    queryKey: scopedKey(user.workspace_id, "exports"),
    path: "/exports",
    refetchInterval: 2000,
  });
  return (
    <>
      <Heading
        eyebrow="YOUR DATA, YOUR CONTROL"
        title="设置与数据管理"
        text="你的研究资料可以独立保存。导出保留对象关系、历史判断和原始 PDF 版本。"
      />
      <section className="panel export-card">
        <div className="export-icon">
          <Archive size={26} />
        </div>
        <h2>导出个人科研档案</h2>
        <p>
          包含课题、研究线索、证据、假设、决策及修订、任务、笔记和关联关系。每个原始文件包含完整性摘要。
        </p>
        <ExportControl
          workspaceId={user.workspace_id}
          canCreate={
            !jobs.isPending &&
            !jobs.error &&
            !jobs.pageError &&
            !jobs.data.data.some((job) =>
              ["queued", "running"].includes(job.status),
            )
          }
          refreshList={() => jobs.refetch({ throwOnError: true })}
        />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>导出记录</h2>
          <span className="muted">完成后的下载链接保留 24 小时</span>
        </div>
        {jobs.isPending ? (
          <Loading />
        ) : jobs.error ? (
          <ErrorBox error={jobs.error} retry={() => jobs.refetch()} />
        ) : jobs.data.data.length ? (
          jobs.data.data.map((job) => (
            <div className="export-row" key={job.id}>
              <div>
                <strong>
                  个人科研档案 ·{" "}
                  {job.include_files ? "含原始文件" : "仅结构化记录"}
                </strong>
                <p>
                  {new Date(job.created_at).toLocaleString("zh-CN", {
                    timeZone: "Asia/Hong_Kong",
                  })}
                  {job.snapshot_at &&
                    ` · 快照 ${new Date(job.snapshot_at).toLocaleTimeString("zh-CN")}`}
                </p>
                {job.error_code && (
                  <p className="export-error">
                    {["queued", "running"].includes(job.status)
                      ? "上次尝试未完成，后台正在继续处理。"
                      : "未生成完整成功档案。"}
                    {exportFailure(job.error_code)}
                  </p>
                )}
              </div>
              <span className="badge">
                {exportExpired(job)
                  ? "已过期"
                  : (exportNames[job.status] ?? job.status)}
              </span>
              {exportExpired(job) && (
                <p>档案已过期。如需新的资料快照，请明确创建新导出。</p>
              )}
              <ExportDownload job={job} workspaceId={user.workspace_id} />
            </div>
          ))
        ) : (
          <Empty
            title="还没有导出档案"
            text="创建一次完整导出，为你的研究资料保留一份独立副本。"
          />
        )}
        <PaginationControls query={jobs} label="导出记录" />
      </section>
      <section className="panel privacy-card">
        <ShieldCheck size={21} />
        <div>
          <h2>私有资料与来源保护</h2>
          <p>
            归档不会删除资料；被证据引用的 PDF
            不能直接移除。账户删除会移除在线资料和全部历史；执行前会列出影响并验证登录密码。
          </p>
        </div>
      </section>
      <section className="panel">
        <h2>删除个人账户</h2>
        <p>请先导出需要保留的研究资料。归档课题不会删除数据。</p>
        <DeletionControl scope="account" workspaceId={user.workspace_id} />
      </section>
    </>
  );
}
