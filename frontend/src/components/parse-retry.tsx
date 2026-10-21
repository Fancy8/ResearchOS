"use client";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { researchRequest, SAFE_REPLAY_AGE_MS } from "@/lib/research-request";
import type { components } from "@/lib/generated-contracts";
import { ErrorBox } from "./common";
import { Button } from "./ui/button";

export function ParseRetry({
  workspaceId,
  paperId,
  fileId,
  status,
  available,
}: {
  workspaceId: string;
  paperId: string;
  fileId: string;
  status: string;
  available: boolean;
}) {
  const cache = useQueryClient();
  const attempt = useRef<{ key: string; createdAt: number } | null>(null);
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [readError, setReadError] = useState<unknown>();
  const [receipt, setReceipt] = useState<components["ParseRetryPublic"]>();
  const [latest, setLatest] = useState<components["ParseStatusPublic"]>();
  async function submit(newIntent = false) {
    if (busy.current) return;
    if (
      attempt.current &&
      Date.now() - attempt.current.createdAt >= SAFE_REPLAY_AGE_MS
    ) {
      setError(
        new Error(
          "原解析请求已超过可安全重试时限。请先读取文件状态并核对处理结果。",
        ),
      );
      return;
    }
    if (newIntent) {
      if (attempt.current || latest?.parse_status !== "failed") return;
      attempt.current = null;
      setReceipt(undefined);
      setLatest(undefined);
    }
    attempt.current ??= { key: crypto.randomUUID(), createdAt: Date.now() };
    busy.current = true;
    setPending(true);
    setError(undefined);
    try {
      const result = await researchRequest<components["ParseRetryPublic"]>(
        `/papers/${paperId}/files/${fileId}/parse-retry`,
        "POST",
        {},
        attempt.current.key,
      );
      setReceipt(result.data);
      attempt.current = null;
      setLatest(undefined);
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    } catch (reason) {
      setError(reason);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  async function read() {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setReadError(undefined);
    try {
      setLatest(
        (
          await researchRequest<components["ParseStatusPublic"]>(
            `/papers/${paperId}/parse-status?file_id=${fileId}`,
          )
        ).data,
      );
      void cache.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    } catch (reason) {
      setReadError(reason);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  if (!attempt.current && !receipt && (!available || status !== "failed"))
    return null;
  const names: Record<string, string> = {
    pending: "等待上传",
    queued: "等待解析",
    processing: "解析中",
    ready: "解析完成",
    failed: "解析失败",
  };
  return (
    <section className="parse-retry-feedback" aria-label="解析重试状态">
      {!attempt.current && !receipt && (
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={() => submit()}
        >
          重试解析
        </Button>
      )}
      {Boolean(error) && <ErrorBox error={error} />}
      {attempt.current && (
        <>
          <p>解析请求结果尚未确认。重试会核对原请求，不新建另一项任务。</p>
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={() => submit()}
          >
            重试原解析请求
          </Button>
        </>
      )}
      {receipt && (
        <p role="status">解析请求已接收，后台处理结果以文件状态为准。</p>
      )}
      {(attempt.current || receipt) && (
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={read}
        >
          读取最新解析状态
        </Button>
      )}
      {Boolean(readError) && <ErrorBox error={readError} />}
      {latest && (
        <p role="status">
          当前文件状态：{names[latest.parse_status] ?? latest.parse_status}。
        </p>
      )}
      {receipt && !attempt.current && latest?.parse_status === "failed" && (
        <Button
          type="button"
          variant="outline"
          disabled={pending || !available}
          onClick={() => submit(true)}
        >
          再次发起解析（新任务）
        </Button>
      )}
    </section>
  );
}
