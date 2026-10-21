"use client";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { ApiError } from "@/lib/api";
import { researchRequest, SAFE_REPLAY_AGE_MS } from "@/lib/research-request";
import {
  checkExportJob,
  exportExpired,
  exportFailure,
  exportKey,
  exportNames,
  readExportIntent,
  readExportJob,
  saveExportIntent,
  type ExportIntent,
  type ExportJob,
} from "@/lib/export-recovery";
import { scopedKey } from "@/lib/query-client";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";
import { ExportDownload } from "./export-download";

export function ExportControl({
  workspaceId,
  canCreate,
  refreshList,
}: {
  workspaceId: string;
  canCreate: boolean;
  refreshList: () => Promise<unknown>;
}) {
  const cache = useQueryClient();
  const [includeFiles, setIncludeFiles] = useState(true);
  const [record, setRecord] = useState<ExportIntent>();
  const original = useRef<ExportIntent | undefined>(undefined);
  const [loaded, setLoaded] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [readError, setReadError] = useState<unknown>();
  const [storageError, setStorageError] = useState<unknown>();
  const [storageBlocked, setStorageBlocked] = useState(false);
  const busy = useRef(false);
  const alive = useRef(false);
  const generation = useRef(0);
  const details = useQuery({
    queryKey: scopedKey(workspaceId, "export-detail", record?.jobId ?? ""),
    queryFn: () =>
      readExportJob(workspaceId, record!.jobId!, record!.includeFiles),
    enabled: record?.phase === "accepted",
    retry: false,
    refetchInterval: (query) =>
      query.state.error
        ? false
        : ["queued", "running"].includes(query.state.data?.status ?? "")
          ? 2000
          : false,
  });
  function adopt(value?: ExportIntent) {
    original.current = value;
    setRecord(value);
  }
  function sync() {
    try {
      let next = readExportIntent(workspaceId);
      const known = original.current;
      if (
        known?.phase === "accepted" &&
        next?.phase === "unknown" &&
        next.key === known.key &&
        next.includeFiles === known.includeFiles
      )
        next = known;
      adopt(next);
      setStorageBlocked(false);
      return next;
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
      if (event.key !== exportKey(workspaceId) && event.key !== null) return;
      generation.current++;
      busy.current = false;
      setPending(false);
      setReadError(undefined);
      setStorageError(undefined);
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
      window.removeEventListener("storage", changed);
    };
    // Controller lifetime follows the authenticated workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);
  async function locked(
    action: (
      fresh: ExportIntent | undefined,
      active: () => boolean,
    ) => Promise<void>,
    options: { read?: boolean; corrupt?: boolean } = {},
  ) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    if (options.read) setReadError(undefined);
    else setError(undefined);
    const token = generation.current;
    const active = () => alive.current && token === generation.current;
    try {
      if (!navigator.locks)
        throw new Error(
          "当前浏览器不支持安全的多窗口导出恢复，请使用受支持的浏览器。",
        );
      await navigator.locks.request(
        `researchos.export.${workspaceId}`,
        { mode: "exclusive", ifAvailable: true },
        async (lock) => {
          if (!lock)
            throw new Error(
              "另一个标签页正在处理导出请求，请等候并重新读取恢复记录。",
            );
          const fresh = options.corrupt ? undefined : sync();
          if (active()) await action(fresh, active);
        },
      );
    } catch (reason) {
      if (active()) {
        if (options.read) setReadError(reason);
        else setError(reason);
      }
    } finally {
      if (active()) {
        busy.current = false;
        setPending(false);
      }
    }
  }
  function save(value: ExportIntent) {
    try {
      saveExportIntent(value);
      setStorageBlocked(false);
      setStorageError(undefined);
    } catch (reason) {
      setStorageBlocked(true);
      throw reason;
    }
    adopt(value);
    return value;
  }
  function same(fresh?: ExportIntent, expected?: ExportIntent) {
    if (!fresh || (expected && fresh.key !== expected.key))
      throw new Error("导出恢复记录已在其他窗口改变，请先核对当前请求。");
    return fresh;
  }
  async function send(value: ExportIntent, active: () => boolean) {
    if (value.phase === "accepted") return;
    if (Date.now() - value.createdAt >= SAFE_REPLAY_AGE_MS)
      throw new Error(
        "原导出请求已超过可安全重试时限。请先核对导出记录，不要直接新建档案。",
      );
    try {
      const job = checkExportJob(
        (
          await researchRequest<ExportJob>(
            "/exports",
            "POST",
            { include_files: value.includeFiles },
            value.key,
          )
        ).data,
        workspaceId,
        { includeFiles: value.includeFiles },
      );
      if (!active()) return;
      const accepted: ExportIntent = {
        ...value,
        phase: "accepted",
        jobId: job.id,
      };
      delete accepted.rejection;
      adopt(accepted);
      try {
        save(accepted);
      } catch (reason) {
        setStorageError(reason);
      }
      // The immutable receipt only acknowledges creation. Query the job separately;
      // an old queued receipt must never replace a newer observed terminal status.
      void cache.invalidateQueries({
        queryKey: scopedKey(workspaceId, "exports"),
      });
    } catch (reason) {
      if (
        active() &&
        reason instanceof ApiError &&
        reason.code === "EXPORT_IN_PROGRESS"
      ) {
        const rejected: ExportIntent = {
          ...value,
          phase: "rejected",
          rejection: "EXPORT_IN_PROGRESS",
        };
        adopt(rejected);
        try {
          save(rejected);
        } catch (storage) {
          setStorageError(storage);
        }
      }
      throw reason;
    }
  }
  async function submit() {
    const expected = original.current;
    const selected = includeFiles;
    await locked(async (fresh, active) => {
      const value = fresh
        ? same(fresh, expected)
        : expected
          ? same(undefined, expected)
          : save({
              version: 1,
              workspaceId,
              key: crypto.randomUUID(),
              createdAt: Date.now(),
              includeFiles: selected,
              phase: "unknown",
            });
      await send(value, active);
    });
  }
  async function read() {
    const expected = original.current;
    await locked(
      async (fresh, active) => {
        const value = same(fresh, expected);
        if (value.phase === "accepted") {
          const job = await readExportJob(
            workspaceId,
            value.jobId!,
            value.includeFiles,
          );
          if (!active()) return;
          cache.setQueryData(
            scopedKey(workspaceId, "export-detail", value.jobId!),
            job,
          );
          try {
            save(value);
          } catch (reason) {
            setStorageError(reason);
          }
        } else await refreshList();
      },
      { read: true },
    );
  }
  async function beginNew() {
    const expected = original.current;
    await locked(
      async (fresh, active) => {
        const value = same(fresh, expected);
        if (value.phase === "unknown")
          throw new Error("原导出结果尚未确认，请先恢复原请求。");
        if (value.phase === "accepted") {
          const job = await readExportJob(
            workspaceId,
            value.jobId!,
            value.includeFiles,
          );
          if (!active()) return;
          cache.setQueryData(
            scopedKey(workspaceId, "export-detail", value.jobId!),
            job,
          );
          if (["queued", "running"].includes(job.status))
            throw new Error("原导出仍在后台处理，请等待完成后再创建新的档案。");
        }
        localStorage.removeItem(exportKey(workspaceId));
        setIncludeFiles(value.includeFiles);
        adopt(undefined);
        setStorageBlocked(false);
        setStorageError(undefined);
        setReadError(undefined);
      },
      { read: true },
    );
  }
  async function forget() {
    await locked(
      async () => {
        localStorage.removeItem(exportKey(workspaceId));
        adopt(undefined);
        setStorageBlocked(false);
        setStorageError(undefined);
        setReadError(undefined);
      },
      { corrupt: true },
    );
  }
  const latest =
    record?.jobId &&
    details.data?.id === record.jobId &&
    details.data.workspace_id === workspaceId &&
    details.data.include_files === record.includeFiles
      ? details.data
      : undefined;
  return (
    <div className="export-control" aria-label="导出请求与恢复">
      <label className="checkbox-line">
        <input
          type="checkbox"
          checked={record?.includeFiles ?? includeFiles}
          disabled={!loaded || Boolean(record) || pending || storageBlocked}
          onChange={(event) => setIncludeFiles(event.target.checked)}
        />
        包含原始 PDF 文件（所有保留版本）
      </label>
      {!record && (
        <>
          <Button
            type="button"
            disabled={!loaded || pending || storageBlocked || !canCreate}
            onClick={submit}
          >
            <Download size={16} />
            {pending ? "正在创建导出任务…" : "创建导出档案"}
          </Button>
          {loaded && !canCreate && (
            <p>请先核对导出记录；已有任务正在处理或记录暂时不可读取。</p>
          )}
        </>
      )}
      {record?.phase === "unknown" && (
        <>
          <p>
            导出请求结果尚未确认。重试会保留原选项与原请求，不另建一份档案。
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={pending || storageBlocked}
            onClick={submit}
          >
            重试原导出请求
          </Button>
        </>
      )}
      {record?.phase === "rejected" && (
        <>
          <p>
            服务端未创建本次导出：已有另一项导出任务。可核对记录后重试原请求。
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={pending || storageBlocked}
            onClick={submit}
          >
            重试原导出请求
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={pending || storageBlocked}
            onClick={beginNew}
          >
            修改选项，开始新的请求
          </Button>
        </>
      )}
      {record?.phase === "accepted" && (
        <div aria-label="原导出任务状态">
          <p role="status">导出请求已接收，后台处理结果以任务状态为准。</p>
          <p>本次档案：{record.includeFiles ? "含原始文件" : "仅结构化记录"}</p>
          {details.isPending && <p role="status">正在读取原导出任务…</p>}
          {Boolean(details.error) && (
            <>
              <p>原请求已接收，状态读取暂未完成。重读不会创建新任务。</p>
              <ErrorBox error={details.error} />
            </>
          )}
          {latest && (
            <>
              <p role="status">
                原任务状态：
                {exportExpired(latest) ? "已过期" : exportNames[latest.status]}
                {latest.status === "running" ? ` ${latest.progress}%` : ""}。
              </p>
              {latest.error_code && (
                <p>
                  {["queued", "running"].includes(latest.status)
                    ? "上次尝试未完成，后台正在继续处理。"
                    : "没有生成完整成功档案。"}
                  {exportFailure(latest.error_code)}
                </p>
              )}
              {exportExpired(latest) && (
                <p>原档案已过期，需要时请明确创建新的档案。</p>
              )}
              <ExportDownload job={latest} workspaceId={workspaceId} />
            </>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={
              pending ||
              storageBlocked ||
              !latest ||
              ["queued", "running"].includes(latest.status)
            }
            onClick={beginNew}
          >
            开始新的导出
          </Button>
        </div>
      )}
      {record && (
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={read}
        >
          读取原导出状态
        </Button>
      )}
      {Boolean(error) && <ErrorBox error={error} />}
      {Boolean(readError) && (
        <>
          <p>读取暂未完成，原导出请求仍保留。</p>
          <ErrorBox error={readError} />
        </>
      )}
      {Boolean(storageError) && (
        <>
          <p>服务端结果已确认，本机恢复记录暂未保存。请先读取原状态。</p>
          <ErrorBox error={storageError} />
        </>
      )}
      {storageBlocked && (
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={() => {
            try {
              sync();
              setError(undefined);
            } catch (reason) {
              setError(reason);
            }
          }}
        >
          重新读取恢复记录
        </Button>
      )}
      {(record || storageBlocked) && (
        <details>
          <summary>管理本机导出恢复记录</summary>
          <p>
            请先核对下方导出记录。清除本机记录不会取消原任务或删除原档案，未核对就重建可能产生重复档案。
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={forget}
          >
            已核对，清除本机导出恢复记录
          </Button>
        </details>
      )}
    </div>
  );
}
