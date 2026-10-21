import { stages } from "./types";

export type CreationKind = "project" | "thread" | "note";
export type CreationRecord = {
  version: 1;
  workspaceId: string;
  kind: CreationKind;
  key: string;
  createdAt: number;
  parentId: string | null;
  contextTitle: string;
  body: Record<string, string>;
  phase: "unknown" | "editable" | "accepted";
  resourceId?: string;
};
export class CreationStorageError extends Error {}
const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const object = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
export const creationKey = (workspaceId: string, kind: CreationKind) =>
  `researchos.${workspaceId}.create.${kind}`;
export function validCreation(
  value: unknown,
  workspaceId: string,
  kind: CreationKind,
): value is CreationRecord {
  if (
    !object(value) ||
    Object.keys(value).some(
      (key) =>
        ![
          "version",
          "workspaceId",
          "kind",
          "key",
          "createdAt",
          "parentId",
          "contextTitle",
          "body",
          "phase",
          "resourceId",
        ].includes(key),
    )
  )
    return false;
  if (
    value.version !== 1 ||
    value.workspaceId !== workspaceId ||
    value.kind !== kind ||
    !uuid(value.key) ||
    typeof value.createdAt !== "number" ||
    !Number.isFinite(value.createdAt) ||
    value.createdAt <= 0 ||
    value.createdAt > Date.now() + 60_000 ||
    typeof value.contextTitle !== "string" ||
    value.contextTitle.length > 250 ||
    !(kind === "thread" ? uuid(value.parentId) : value.parentId === null) ||
    !["unknown", "editable", "accepted"].includes(String(value.phase)) ||
    !object(value.body)
  )
    return false;
  if (
    value.phase === "accepted"
      ? !uuid(value.resourceId)
      : value.resourceId !== undefined
  )
    return false;
  const limits: Record<string, number> =
    kind === "project"
      ? { title: 250, description: 20000, research_stage: 32 }
      : kind === "thread"
        ? { title: 250, question: 20000, description: 20000 }
        : { title: 250 };
  const body = value.body;
  if (
    Object.keys(body).length !== Object.keys(limits).length ||
    Object.keys(body).some(
      (key) => !Object.prototype.hasOwnProperty.call(limits, key),
    )
  )
    return false;
  if (
    Object.entries(limits).some(
      ([key, limit]) =>
        typeof body[key] !== "string" ||
        (body[key] as string).length > limit ||
        /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(body[key] as string),
    )
  )
    return false;
  return (
    kind !== "project" ||
    Object.keys(stages).includes(body.research_stage as string)
  );
}
export function readCreation(
  workspaceId: string,
  kind: CreationKind,
): CreationRecord | undefined {
  const raw = localStorage.getItem(creationKey(workspaceId, kind));
  if (raw === null) return;
  let value: unknown;
  try {
    if (raw.length > 300_000) throw new Error();
    value = JSON.parse(raw);
  } catch {
    throw new Error("本机创建恢复记录损坏，请先核对已有记录。");
  }
  if (!validCreation(value, workspaceId, kind))
    throw new Error("本机创建恢复记录无效或时钟发生回退，已阻止自动提交。");
  return value;
}
export function saveCreation(value: CreationRecord) {
  if (!validCreation(value, value.workspaceId, value.kind))
    throw new Error("创建输入过长或包含不支持的字符，请修正后保存。");
  const raw = JSON.stringify(value);
  try {
    localStorage.setItem(creationKey(value.workspaceId, value.kind), raw);
    if (
      localStorage.getItem(creationKey(value.workspaceId, value.kind)) !== raw
    )
      throw new Error();
  } catch {
    throw new CreationStorageError(
      "无法保存本机创建恢复记录。请检查浏览器存储后重试，输入仍保留。",
    );
  }
}
export function sameCreation(a: CreationRecord, b: CreationRecord) {
  return (
    a.key === b.key &&
    a.kind === b.kind &&
    a.workspaceId === b.workspaceId &&
    a.parentId === b.parentId &&
    a.createdAt === b.createdAt &&
    a.contextTitle === b.contextTitle &&
    Object.keys(a.body).every((key) => a.body[key] === b.body[key])
  );
}
export function creationEndpoint(value: CreationRecord) {
  return value.kind === "thread"
    ? `/projects/${value.parentId}/threads`
    : value.kind === "project"
      ? "/projects"
      : "/notes";
}
export function creationObjectPath(value: CreationRecord) {
  return `/${value.kind === "project" ? "projects" : value.kind === "thread" ? "threads" : "notes"}/${value.resourceId}`;
}
export function checkCreated(
  value: unknown,
  intent: CreationRecord,
  expectedId?: string,
) {
  if (
    !object(value) ||
    !uuid(value.id) ||
    value.workspace_id !== intent.workspaceId ||
    (expectedId && value.id !== expectedId) ||
    (intent.kind === "thread" && value.project_id !== intent.parentId) ||
    typeof value.title !== "string" ||
    typeof value.version !== "number" ||
    !Number.isSafeInteger(value.version) ||
    value.version < 1
  )
    throw new Error("创建回执与原目标不一致，结果尚未确认。请核对已有记录。");
  return { id: value.id, title: value.title, version: value.version };
}
