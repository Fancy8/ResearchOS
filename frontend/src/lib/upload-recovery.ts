import { ApiError, csrfToken } from "./api";
import type { components } from "./generated-contracts";

export type UploadPhase =
  | "preflight"
  | "duplicates"
  | "init"
  | "transfer"
  | "complete"
  | "accepted"
  | "terminal";
export type InitializedUpload = Pick<
  components["UploadInitializedPublic"],
  "upload_id" | "paper_id" | "paper_file_id" | "expires_at"
>;
export type UploadReceipt = Pick<
  components["UploadCompletedPublic"],
  "upload_id" | "paper_file_id" | "job_id" | "status"
>;
export type UploadRecord = {
  version: 1;
  workspaceId: string;
  id: string;
  createdAt: number;
  phase: UploadPhase;
  name: string;
  size: number;
  sha256: string;
  paperId: string | null;
  projectId: string | null;
  projectTitle: string;
  initKey: string;
  completeKey: string;
  initialized?: InitializedUpload;
  receipt?: UploadReceipt;
  terminalReason?: "expired" | "failed" | "rejected";
};
const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const date = (v: unknown) =>
  typeof v === "string" && Number.isFinite(Date.parse(v));
export const uploadKey = (workspaceId: string) =>
  `researchos.${workspaceId}.upload`;
export function validUpload(
  value: unknown,
  workspaceId: string,
): value is UploadRecord {
  if (
    !object(value) ||
    value.version !== 1 ||
    value.workspaceId !== workspaceId ||
    !uuid(value.id) ||
    !uuid(value.initKey) ||
    !uuid(value.completeKey) ||
    typeof value.createdAt !== "number" ||
    !Number.isFinite(value.createdAt) ||
    value.createdAt <= 0 ||
    ![
      "preflight",
      "duplicates",
      "init",
      "transfer",
      "complete",
      "accepted",
      "terminal",
    ].includes(String(value.phase)) ||
    typeof value.name !== "string" ||
    !value.name.length ||
    value.name.length > 250 ||
    typeof value.projectTitle !== "string" ||
    value.projectTitle.length > 250 ||
    !Number.isInteger(value.size) ||
    Number(value.size) <= 0 ||
    Number(value.size) > 50 * 1024 * 1024 ||
    typeof value.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.sha256) ||
    !(value.paperId === null || uuid(value.paperId)) ||
    !(value.projectId === null || uuid(value.projectId))
  )
    return false;
  const allowed = [
    "version",
    "workspaceId",
    "id",
    "createdAt",
    "phase",
    "name",
    "size",
    "sha256",
    "paperId",
    "projectId",
    "projectTitle",
    "initKey",
    "completeKey",
    "initialized",
    "receipt",
    "terminalReason",
  ];
  if (Object.keys(value).some((key) => !allowed.includes(key))) return false;
  const init = value.initialized;
  if (
    init !== undefined &&
    (!object(init) ||
      !uuid(init.upload_id) ||
      !uuid(init.paper_id) ||
      !uuid(init.paper_file_id) ||
      !date(init.expires_at) ||
      (value.paperId !== null && init.paper_id !== value.paperId) ||
      Object.keys(init).some(
        (key) =>
          !["upload_id", "paper_id", "paper_file_id", "expires_at"].includes(
            key,
          ),
      ))
  )
    return false;
  if (
    ["transfer", "complete", "accepted"].includes(String(value.phase)) &&
    !object(init)
  )
    return false;
  const receipt = value.receipt;
  if (
    receipt !== undefined &&
    (!object(receipt) ||
      !object(init) ||
      !uuid(receipt.job_id) ||
      receipt.upload_id !== init.upload_id ||
      receipt.paper_file_id !== init.paper_file_id ||
      !["queued", "running", "succeeded", "failed"].includes(
        String(receipt.status),
      ) ||
      Object.keys(receipt).some(
        (key) =>
          !["upload_id", "paper_file_id", "job_id", "status"].includes(key),
      ))
  )
    return false;
  if (value.phase === "accepted" && !object(receipt)) return false;
  if (
    value.terminalReason !== undefined &&
    !["expired", "failed", "rejected"].includes(String(value.terminalReason))
  )
    return false;
  return true;
}
export function readUpload(workspaceId: string): UploadRecord | undefined {
  const raw = localStorage.getItem(uploadKey(workspaceId));
  if (raw === null) return;
  if (raw.length > 16_384)
    throw new Error("本地上传恢复记录过大，无法安全读取。请先核对文献列表。");
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error("本地上传恢复记录损坏，请先核对文献列表。");
  }
  if (!validUpload(value, workspaceId))
    throw new Error("本地上传恢复记录无效，已阻止自动继续。请先核对文献列表。");
  return value;
}
export function saveUpload(record: UploadRecord) {
  if (!validUpload(record, record.workspaceId))
    throw new Error("上传恢复信息不完整，尚未安全记录。");
  const raw = JSON.stringify(record);
  try {
    localStorage.setItem(uploadKey(record.workspaceId), raw);
    if (localStorage.getItem(uploadKey(record.workspaceId)) !== raw)
      throw new Error();
  } catch {
    throw new Error("无法保存本地上传恢复记录。请检查浏览器存储后重试。");
  }
}
export async function hashFile(file: File) {
  if (!file.size || file.size > 50 * 1024 * 1024)
    throw new Error("请选择大小为 1 字节至 50 MiB 的 PDF 文件。");
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
    ),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}
export function transferUpload(
  initialized: InitializedUpload,
  file: File,
  progress: (value: number) => void,
  signal: AbortSignal,
) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    let settled = false;
    const abort = () => request.abort();
    function finish(error?: unknown) {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve();
    }
    request.open("POST", `/api/v1/uploads/${initialized.upload_id}/content`);
    request.withCredentials = true;
    request.timeout = 600_000;
    request.setRequestHeader("X-CSRF-Token", csrfToken());
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        progress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      try {
        const payload = JSON.parse(request.responseText);
        if (request.status < 200 || request.status >= 300) {
          finish(
            new ApiError(
              request.status,
              payload.error?.code ?? "UPLOAD_FAILED",
              payload.error?.message ?? "文件传输失败",
            ),
          );
          return;
        }
        if (
          payload.data?.upload_id !== initialized.upload_id ||
          payload.data?.bytes_received !== file.size
        )
          throw new Error();
        finish();
      } catch {
        finish(new Error("传输回执无法确认，请核对原上传会话后重试。"));
      }
    };
    request.onerror = () =>
      finish(new Error("文件传输中断，结果尚未确认。请继续同一上传会话。"));
    request.ontimeout = () =>
      finish(new Error("文件传输等待超时，结果尚未确认。请继续同一上传会话。"));
    request.onabort = () =>
      finish(new Error("文件传输已暂停，结果尚未确认。可继续同一会话。"));
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      finish(new Error("文件传输已暂停"));
      return;
    }
    const body = new FormData();
    body.append("file", file);
    request.send(body);
  });
}
