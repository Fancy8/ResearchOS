"use client";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { researchRequest, SAFE_REPLAY_AGE_MS } from "./research-request";
import {
  hashFile,
  readUpload,
  saveUpload,
  transferUpload,
  uploadKey,
  validUpload,
  type UploadRecord,
  type InitializedUpload,
  type UploadReceipt,
} from "./upload-recovery";
import type { components } from "./generated-contracts";
import type { Project } from "./types";

export type UploadResult = InitializedUpload & { upload_url: string };
type Duplicate = components["DuplicatePublic"];
type Snapshot = {
  upload: components["UploadStatusPublic"];
  parse: components["ParseStatusPublic"];
};
type Context = {
  paperId?: string;
  current?: Project;
  onFinish?: (value: UploadResult) => void | Promise<void>;
};

export function useUpload(workspaceId: string, context: Context) {
  const cache = useQueryClient();
  const [record, setRecord] = useState<UploadRecord>();
  const recordRef = useRef<UploadRecord | undefined>(undefined);
  const file = useRef<{ id: string; value: File } | undefined>(undefined);
  const [hasFile, setHasFile] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const generation = useRef(0);
  const alive = useRef(false);
  const abort = useRef<AbortController | undefined>(undefined);
  const [error, setError] = useState<unknown>();
  const [refreshError, setRefreshError] = useState<unknown>();
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [working, setWorking] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [duplicates, setDuplicates] = useState<Duplicate[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot>();

  function adopt(value?: UploadRecord) {
    recordRef.current = value;
    setRecord(value);
    if (!value || file.current?.id !== value.id || value.phase === "accepted") {
      file.current = undefined;
      setHasFile(false);
    }
  }
  function sync() {
    try {
      let value = readUpload(workspaceId);
      const known = recordRef.current;
      // A failed local receipt save must not downgrade an in-memory known success.
      if (
        known?.phase === "accepted" &&
        value?.phase === "complete" &&
        value.id === known.id &&
        value.initKey === known.initKey &&
        value.completeKey === known.completeKey &&
        value.initialized?.upload_id === known.initialized?.upload_id
      )
        value = known;
      setStorageBlocked(false);
      adopt(value);
      return value;
    } catch (reason) {
      setStorageBlocked(true);
      throw reason;
    }
  }
  useEffect(() => {
    alive.current = true;
    generation.current++;
    try {
      sync();
    } catch (reason) {
      setError(reason);
    }
    setLoaded(true);
    const changed = (event: StorageEvent) => {
      if (event.key !== uploadKey(workspaceId) && event.key !== null) return;
      generation.current++;
      abort.current?.abort();
      busy.current = false;
      setPending(false);
      setProgress(null);
      setSnapshot(undefined);
      setDuplicates([]);
      setCursor(null);
      try {
        sync();
        setError(undefined);
      } catch (reason) {
        setError(reason);
      }
    };
    window.addEventListener("storage", changed);
    return () => {
      alive.current = false;
      generation.current++;
      abort.current?.abort();
      file.current = undefined;
      window.removeEventListener("storage", changed);
    };
    // One controller per mounted workspace. React remounts it across identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  async function locked(
    action: (
      fresh: UploadRecord | undefined,
      active: () => boolean,
    ) => Promise<void>,
    allowCorrupt = false,
  ) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError(undefined);
    setSnapshot(undefined);
    const token = generation.current;
    const active = () => alive.current && generation.current === token;
    try {
      if (!navigator.locks)
        throw new Error(
          "当前浏览器不支持安全的多窗口上传恢复，请使用受支持的浏览器。",
        );
      await navigator.locks.request(
        `researchos.upload.${workspaceId}`,
        { mode: "exclusive", ifAvailable: true },
        async (lock) => {
          if (!lock)
            throw new Error(
              "另一个标签页正在处理本次上传。请等待完成后重新读取恢复记录。",
            );
          const fresh = allowCorrupt ? undefined : sync();
          if (active()) await action(fresh, active);
        },
      );
    } catch (reason) {
      if (active()) setError(reason);
    } finally {
      if (active()) {
        busy.current = false;
        setPending(false);
        setWorking("");
        setProgress(null);
        abort.current = undefined;
      }
    }
  }
  function persist(value: UploadRecord) {
    try {
      saveUpload(value);
    } catch (reason) {
      setStorageBlocked(true);
      throw reason;
    }
    adopt(value);
    setStorageBlocked(false);
    return value;
  }
  function same(fresh: UploadRecord | undefined, expected?: UploadRecord) {
    if (!fresh || (expected && fresh.id !== expected.id))
      throw new Error("上传恢复记录已在其他窗口改变，请核对当前文件后继续。");
    return fresh;
  }
  function safeReplay(value: UploadRecord) {
    if (Date.now() - value.createdAt >= SAFE_REPLAY_AGE_MS)
      throw new Error(
        "原请求已超过可安全重试时限。请先核对文献与文件状态，再决定是否结束本次恢复。",
      );
  }
  async function session(value: UploadRecord) {
    const init = value.initialized!;
    const result = (
      await researchRequest<components["UploadStatusPublic"]>(
        `/uploads/${init.upload_id}`,
      )
    ).data;
    if (
      result.id !== init.upload_id ||
      result.paper_id !== init.paper_id ||
      result.paper_file_id !== init.paper_file_id
    )
      throw new Error("上传状态与原会话不一致，已停止自动继续。");
    return result;
  }
  async function refresh(value: UploadRecord) {
    void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    const init = value.initialized;
    if (
      !init ||
      !context.onFinish ||
      (context.paperId
        ? context.paperId !== init.paper_id
        : value.paperId !== null)
    )
      return;
    const token = generation.current;
    try {
      await context.onFinish({
        ...init,
        upload_url: `/api/v1/uploads/${init.upload_id}/content`,
      });
    } catch (reason) {
      if (alive.current && token === generation.current)
        setRefreshError(reason);
    }
  }
  async function inspect(value: UploadRecord, active: () => boolean) {
    if (!value.initialized)
      throw new Error("初始化回执尚未确认，请先继续原上传请求。");
    setWorking("读取原上传与解析状态…");
    const [upload, parse] = await Promise.all([
      session(value),
      researchRequest<components["ParseStatusPublic"]>(
        `/papers/${value.initialized.paper_id}/parse-status?file_id=${value.initialized.paper_file_id}`,
      ).then((result) => result.data),
    ]);
    if (parse.paper_file_id !== value.initialized.paper_file_id)
      throw new Error("文件状态与原上传不一致，已停止刷新。");
    if (active()) {
      setSnapshot({ upload, parse });
      if (value.phase === "accepted") {
        try {
          saveUpload(value);
          setRefreshError(undefined);
        } catch (reason) {
          setRefreshError(reason);
        }
      }
      void refresh(value);
    }
  }
  async function drive(value: UploadRecord, active: () => boolean) {
    let next = value;
    if (next.phase === "accepted") {
      await inspect(next, active);
      return;
    }
    if (next.phase === "terminal") {
      await inspect(next, active);
      return;
    }
    if (next.phase === "preflight" || next.phase === "duplicates") {
      setWorking("检查相同文件…");
      if (!next.paperId) {
        const result = await researchRequest<Duplicate[]>(
          `/papers/duplicates?sha256=${next.sha256}`,
        );
        if (!active()) return;
        if (result.data.length) {
          persist({ ...next, phase: "duplicates" });
          setDuplicates(result.data);
          setCursor(result.meta?.next_cursor ?? null);
          return;
        }
      }
      if (!active()) return;
      next = persist({ ...next, phase: "init" });
    }
    if (next.phase === "init") {
      safeReplay(next);
      setWorking("确认原上传初始化…");
      const result = (
        await researchRequest<components["UploadInitializedPublic"]>(
          "/papers/upload-init",
          "POST",
          {
            filename: next.name,
            size_bytes: next.size,
            sha256: next.sha256,
            paper_id: next.paperId,
            project_id: next.projectId,
          },
          next.initKey,
        )
      ).data;
      if (!active()) return;
      if (result.upload_url !== `/api/v1/uploads/${result.upload_id}/content`)
        throw new Error("上传地址与原会话不一致，已停止传输。");
      const initialized = {
        upload_id: result.upload_id,
        paper_id: result.paper_id,
        paper_file_id: result.paper_file_id,
        expires_at: result.expires_at,
      };
      next = persist({ ...next, initialized, phase: "transfer" });
    }
    if (next.phase === "transfer") {
      setWorking("核对原上传会话…");
      let state = await session(next);
      if (!active()) return;
      if (
        state.status === "failed" ||
        state.status === "expired" ||
        (state.status === "pending" &&
          Date.parse(state.expires_at) <= Date.now())
      ) {
        persist({
          ...next,
          phase: "terminal",
          terminalReason: state.status === "failed" ? "failed" : "expired",
        });
        return;
      }
      if (state.status === "pending") {
        if (!file.current || file.current.id !== next.id)
          throw new Error(
            "请重新选择原 PDF。只有大小和 SHA-256 均匹配，才能继续同一上传。",
          );
        const controller = new AbortController();
        abort.current = controller;
        setWorking("传输原 PDF…");
        setProgress(0);
        try {
          await transferUpload(
            next.initialized!,
            file.current.value,
            (value) => {
              if (active()) setProgress(value);
            },
            controller.signal,
          );
        } catch (reason) {
          if (!(reason instanceof ApiError && reason.code === "STATE_CONFLICT"))
            throw reason;
          state = await session(next);
          if (!["validating", "completed"].includes(state.status)) throw reason;
        }
      } else if (!["validating", "completed"].includes(state.status))
        throw new Error("原上传会话处于不可继续的状态，请先核对文件。");
      if (!active()) return;
      next = persist({ ...next, phase: "complete" });
    }
    if (next.phase === "complete") {
      safeReplay(next);
      setWorking("核对后台验证请求…");
      const result = (
        await researchRequest<components["UploadCompletedPublic"]>(
          `/papers/${next.initialized!.paper_id}/upload-complete`,
          "POST",
          { upload_id: next.initialized!.upload_id },
          next.completeKey,
        )
      ).data;
      if (!active()) return;
      const receipt: UploadReceipt = {
        upload_id: result.upload_id,
        paper_file_id: result.paper_file_id,
        job_id: result.job_id,
        status: result.status,
      };
      const accepted: UploadRecord = { ...next, receipt, phase: "accepted" };
      if (!validUpload(accepted, workspaceId))
        throw new Error("后台接收回执与原上传不一致，结果尚未确认。");
      adopt(accepted);
      file.current = undefined;
      setHasFile(false);
      // A local-storage or read failure after this point must not undo a known receipt.
      try {
        saveUpload(accepted);
        setStorageBlocked(false);
      } catch (reason) {
        setRefreshError(reason);
      }
      void refresh(accepted);
    }
  }
  async function run(value: UploadRecord, active: () => boolean) {
    try {
      await drive(value, active);
    } catch (reason) {
      if (
        active() &&
        reason instanceof ApiError &&
        [
          "UPLOAD_EXPIRED",
          "INVALID_PDF",
          "UNSUPPORTED_FILE",
          "FILE_TOO_LARGE",
          "QUOTA_EXCEEDED",
          "VALIDATION_ERROR",
        ].includes(reason.code)
      ) {
        const now = recordRef.current;
        if (now && now.phase !== "accepted")
          persist({
            ...now,
            phase: "terminal",
            terminalReason:
              reason.code === "UPLOAD_EXPIRED" ? "expired" : "rejected",
          });
      }
      throw reason;
    }
  }
  async function choose(candidate: File) {
    // Snapshot target context before hashing or any asynchronous work.
    const target = {
      paperId: context.paperId ?? null,
      projectId: context.current?.id ?? null,
      projectTitle: context.current?.title ?? "未指定课题",
    };
    await locked(async (fresh, active) => {
      setWorking("计算文件摘要…");
      const hash = await hashFile(candidate);
      if (!active()) return;
      let next: UploadRecord;
      if (fresh && !["accepted", "terminal"].includes(fresh.phase)) {
        if (fresh.size !== candidate.size || fresh.sha256 !== hash)
          throw new Error(
            "所选文件与原上传摘要或大小不一致，未替换原会话。请选择原 PDF。",
          );
        next = fresh;
      } else
        next = {
          version: 1,
          workspaceId,
          id: crypto.randomUUID(),
          createdAt: Date.now(),
          phase: "preflight",
          name: candidate.name,
          size: candidate.size,
          sha256: hash,
          ...target,
          initKey: crypto.randomUUID(),
          completeKey: crypto.randomUUID(),
        };
      if (!fresh || fresh.id !== next.id) {
        next = persist(next);
        setDuplicates([]);
        setCursor(null);
        setRefreshError(undefined);
      }
      file.current = { id: next.id, value: candidate };
      setHasFile(true);
      await run(next, active);
    });
  }
  async function resume() {
    const expected = recordRef.current;
    await locked(async (fresh, active) => {
      const next = fresh ? same(fresh, expected) : undefined;
      if (!next) throw new Error("原恢复记录已不存在，请先核对文献列表。");
      await run(next, active);
    });
  }
  async function inspectCurrent() {
    const expected = recordRef.current;
    await locked(async (fresh, active) => {
      await inspect(same(fresh, expected), active);
    });
  }
  async function independentCopy() {
    const expected = recordRef.current;
    await locked(async (fresh, active) => {
      const next = same(fresh, expected);
      if (next.phase !== "duplicates") return;
      await run(persist({ ...next, phase: "init" }), active);
    });
  }
  async function more() {
    const expected = recordRef.current;
    await locked(async (fresh, active) => {
      const next = same(fresh, expected);
      if (next.phase !== "duplicates" || !cursor) return;
      const result = await researchRequest<Duplicate[]>(
        `/papers/duplicates?sha256=${next.sha256}&cursor=${encodeURIComponent(cursor)}`,
      );
      if (active()) {
        setDuplicates((previous) => [
          ...new Map(
            [...previous, ...result.data].map((row) => [
              row.paper_file_id,
              row,
            ]),
          ).values(),
        ]);
        setCursor(result.meta?.next_cursor ?? null);
      }
    });
  }
  async function reuse(candidate: Duplicate) {
    let href: string | undefined;
    const expected = recordRef.current;
    await locked(async (fresh) => {
      const next = same(fresh, expected);
      if (
        next.phase !== "duplicates" ||
        !duplicates.some(
          (row) =>
            row.paper_id === candidate.paper_id &&
            row.paper_file_id === candidate.paper_file_id,
        )
      )
        return;
      localStorage.removeItem(uploadKey(workspaceId));
      file.current = undefined;
      adopt(undefined);
      setDuplicates([]);
      setCursor(null);
      href = `/papers/${candidate.paper_id}?fileId=${candidate.paper_file_id}`;
    });
    return href;
  }
  async function forget() {
    await locked(async () => {
      localStorage.removeItem(uploadKey(workspaceId));
      file.current = undefined;
      adopt(undefined);
      setDuplicates([]);
      setCursor(null);
      setSnapshot(undefined);
      setStorageBlocked(false);
      setRefreshError(undefined);
    }, true);
  }
  return {
    record,
    loaded,
    pending,
    error,
    refreshError,
    storageBlocked,
    working,
    progress,
    duplicates,
    cursor,
    snapshot,
    hasFile,
    choose,
    resume,
    inspect: inspectCurrent,
    independentCopy,
    more,
    reuse,
    forget,
    pause: () => abort.current?.abort(),
    retryRead: async () => {
      if (recordRef.current?.phase === "accepted") await inspectCurrent();
      else
        try {
          sync();
          setError(undefined);
        } catch (reason) {
          setError(reason);
        }
    },
  };
}
