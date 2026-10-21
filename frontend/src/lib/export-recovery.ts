import type { components } from "./generated-contracts";
import { researchRequest } from "./research-request";

export type ExportJob = components["ExportJobPublic"];
export type ExportIntent = {
  version: 1;
  workspaceId: string;
  key: string;
  createdAt: number;
  includeFiles: boolean;
  phase: "unknown" | "accepted" | "rejected";
  jobId?: string;
  rejection?: "EXPORT_IN_PROGRESS";
};
const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
export const exportKey = (workspaceId: string) =>
  `researchos.${workspaceId}.export`;
export function validExportIntent(
  value: unknown,
  workspaceId: string,
): value is ExportIntent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  if (
    Object.keys(v).some(
      (key) =>
        ![
          "version",
          "workspaceId",
          "key",
          "createdAt",
          "includeFiles",
          "phase",
          "jobId",
          "rejection",
        ].includes(key),
    )
  )
    return false;
  if (
    v.version !== 1 ||
    v.workspaceId !== workspaceId ||
    !uuid(v.key) ||
    typeof v.createdAt !== "number" ||
    !Number.isFinite(v.createdAt) ||
    v.createdAt <= 0 ||
    v.createdAt > Date.now() + 60_000 ||
    typeof v.includeFiles !== "boolean"
  )
    return false;
  if (v.phase === "accepted") return uuid(v.jobId) && v.rejection === undefined;
  if (v.phase === "rejected")
    return v.jobId === undefined && v.rejection === "EXPORT_IN_PROGRESS";
  return (
    v.phase === "unknown" && v.jobId === undefined && v.rejection === undefined
  );
}
export function readExportIntent(
  workspaceId: string,
): ExportIntent | undefined {
  const raw = localStorage.getItem(exportKey(workspaceId));
  if (raw === null) return;
  let value: unknown;
  try {
    if (raw.length > 2048) throw new Error();
    value = JSON.parse(raw);
  } catch {
    throw new Error("本机导出恢复记录损坏，请先核对导出记录。");
  }
  if (!validExportIntent(value, workspaceId))
    throw new Error(
      "本机导出恢复记录无效或系统时钟发生回退，已阻止自动提交。请先核对导出记录。",
    );
  return value;
}
export function saveExportIntent(value: ExportIntent) {
  if (!validExportIntent(value, value.workspaceId))
    throw new Error("导出恢复信息不完整，已停止提交。");
  const raw = JSON.stringify(value);
  try {
    localStorage.setItem(exportKey(value.workspaceId), raw);
    if (localStorage.getItem(exportKey(value.workspaceId)) !== raw)
      throw new Error();
  } catch {
    throw new Error("无法保存本机导出恢复记录，请检查浏览器存储后重试。");
  }
}
export function checkExportJob(
  job: ExportJob,
  workspaceId: string,
  expected?: { id?: string; includeFiles: boolean },
) {
  if (
    !job ||
    !uuid(job.id) ||
    job.workspace_id !== workspaceId ||
    (expected?.id && job.id !== expected.id) ||
    typeof job.include_files !== "boolean" ||
    (expected && job.include_files !== expected.includeFiles) ||
    !["queued", "running", "succeeded", "failed", "expired"].includes(
      job.status,
    )
  )
    throw new Error("导出回执与原请求不一致，结果尚未确认。");
  return job;
}
export async function readExportJob(
  workspaceId: string,
  id: string,
  includeFiles: boolean,
) {
  return checkExportJob(
    (await researchRequest<ExportJob>(`/exports/${id}`)).data,
    workspaceId,
    { id, includeFiles },
  );
}
export const exportNames: Record<string, string> = {
  queued: "等待后台处理",
  running: "正在打包与验证",
  succeeded: "已完成",
  failed: "失败",
  expired: "已过期",
};
export function exportExpired(job: ExportJob) {
  return (
    job.status === "expired" ||
    (job.status === "succeeded" &&
      Boolean(job.expires_at) &&
      Date.parse(job.expires_at!) <= Date.now())
  );
}

export function exportFailure(code: string) {
  const reasons: Record<string, string> = {
    EXPORT_SOURCE_HASH_MISMATCH:
      "原始 PDF 的完整性校验未通过，请先核对原文件。",
    EXPORT_REQUIRED_FILE_UNAVAILABLE:
      "被证据引用的原始文件不可用。可核对原件，或明确选择仅导出结构化记录。",
    EXPORT_SOURCE_UNAVAILABLE: "原始文件或存储服务暂不可用，请核对后重试。",
    EXPORT_SNAPSHOT_TIMEOUT:
      "本次资料快照超过处理时限，请稍后重试或联系维护人员。",
    ATTEMPTS_EXHAUSTED: "后台多次尝试仍未完成，请核对原文件和服务状态。",
  };
  return reasons[code] ?? "档案打包未完成，请核对任务状态后重试。";
}
