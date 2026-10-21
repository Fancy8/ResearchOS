"use client";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  exportExpired,
  readExportJob,
  type ExportJob,
} from "@/lib/export-recovery";
import { scopedKey } from "@/lib/query-client";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";

export function ExportDownload({
  job,
  workspaceId,
}: {
  job: ExportJob;
  workspaceId: string;
}) {
  const cache = useQueryClient();
  const busy = useRef(false);
  const attempt = useRef(0);
  const alive = useRef(false);
  const [frame, setFrame] = useState<{ token: number; url: string }>();
  useEffect(() => {
    alive.current = true;
    busy.current = false;
    setPending(false);
    setRequested(false);
    setError(undefined);
    setFrame(undefined);
    return () => {
      alive.current = false;
      attempt.current++;
    };
  }, [workspaceId, job.id]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [requested, setRequested] = useState(false);
  if (job.status !== "succeeded" || exportExpired(job)) return null;
  async function download() {
    if (busy.current) return;
    busy.current = true;
    const token = ++attempt.current;
    setPending(true);
    setError(undefined);
    setRequested(false);
    try {
      const current = await readExportJob(
        workspaceId,
        job.id,
        job.include_files,
      );
      if (!alive.current || token !== attempt.current) return;
      void cache.invalidateQueries({
        queryKey: scopedKey(workspaceId, "exports"),
      });
      void cache.invalidateQueries({
        queryKey: scopedKey(workspaceId, "export-detail", job.id),
      });
      if (
        current.status !== "succeeded" ||
        !current.expires_at ||
        exportExpired(current)
      )
        throw new Error("这份档案已过期或尚不可下载，请读取导出状态后核对。");
      // Native attachment download avoids a multi-GiB Blob; API errors remain in
      // an owned same-origin frame so the application can show them in place.
      setFrame({ token, url: `/api/v1/exports/${job.id}/download` });
      setRequested(true);
    } catch (reason) {
      if (alive.current && token === attempt.current) setError(reason);
    } finally {
      if (alive.current && token === attempt.current) {
        busy.current = false;
        setPending(false);
      }
    }
  }
  return (
    <div className="export-download">
      <Button
        type="button"
        variant="outline"
        disabled={pending}
        onClick={download}
      >
        {pending ? "核对下载状态…" : "下载 ZIP"}
      </Button>
      {requested && (
        <small role="status">已请求下载，请在浏览器下载记录中确认结果。</small>
      )}
      {Boolean(error) && <ErrorBox error={error} />}
      {frame && (
        <iframe
          hidden
          key={frame.token}
          src={frame.url}
          title="导出文件下载"
          onLoad={(event) => {
            if (!alive.current || frame.token !== attempt.current) return;
            try {
              const doc = event.currentTarget.contentDocument;
              if (!doc || doc.URL === "about:blank") return;
              const raw = (
                doc.querySelector("pre")?.textContent ?? doc.body?.textContent
              )?.trim();
              if (!raw) return;
              let message = "下载未能完成，请读取原导出状态后重试。";
              try {
                const payload = JSON.parse(raw);
                if (typeof payload.error?.message === "string")
                  message = payload.error.message;
              } catch {
                /* Non-JSON proxy errors keep the bounded local message. */
              }
              setRequested(false);
              setError(new Error(message));
            } catch {
              setRequested(false);
              setError(
                new Error(
                  "下载结果暂不可读取，请检查浏览器下载记录并核对原任务。",
                ),
              );
            }
          }}
          onError={() => {
            if (alive.current && frame.token === attempt.current) {
              setRequested(false);
              setError(new Error("下载请求未能完成，请读取原导出状态后重试。"));
            }
          }}
        />
      )}
    </div>
  );
}
