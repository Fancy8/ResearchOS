"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, write } from "@/lib/api";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";

type Preview = {
  scope: "account" | "file";
  paper_file_id?: string;
  preview_token: string;
  counts: Record<string, number>;
  effects: string[];
  blocked: boolean;
  backup_retention_days?: number | null;
};
export type DeletionJob = {
  id: string;
  scope: string;
  status: string;
  receipt?: string;
  online_finished_at: string | null;
  backup_expiry_at: string | null;
  backup_status: string;
  error_code: string | null;
};
export function DeletionControl({
  scope,
  targetId,
  workspaceId,
}: {
  scope: "account" | "file";
  targetId?: string;
  workspaceId: string;
}) {
  const router = useRouter();
  const cache = useQueryClient();
  const [preview, setPreview] = useState<Preview>();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  function trackReceipt(result: { id: string; receipt: string }) {
    sessionStorage.setItem(`researchos.deletion.${result.id}`, result.receipt);
    if (scope === "account") {
      for (const key of Object.keys(localStorage))
        if (
          key.startsWith(`researchos.${workspaceId}.`) ||
          key.startsWith(`researchos:draft:${workspaceId}:`)
        )
          localStorage.removeItem(key);
      cache.clear();
    }
    router.replace(`/deletion-status?id=${result.id}`);
  }
  return (
    <div className="deletion-control">
      {!preview ? (
        <Button
          variant="outline"
          disabled={pending}
          onClick={async () => {
            setPending(true);
            setError(undefined);
            try {
              setPreview(
                (
                  await write<Preview>("/deletion-previews", "POST", {
                    scope,
                    target_id: targetId ?? null,
                  })
                ).data,
              );
            } catch (reason) {
              setError(reason);
            } finally {
              setPending(false);
            }
          }}
        >
          {scope === "account" ? "预览账户删除影响" : "预览此文件删除影响"}
        </Button>
      ) : (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setPending(true);
            setError(undefined);
            try {
              const result = (
                await write<DeletionJob>("/deletions", "POST", {
                  scope,
                  target_id: targetId ?? null,
                  preview_token: preview.preview_token,
                  password,
                  confirmation,
                })
              ).data;
              trackReceipt({ id: result.id, receipt: result.receipt! });
            } catch (reason) {
              if (
                reason instanceof ApiError &&
                reason.code === "DELETION_JOURNAL_PENDING"
              ) {
                const receipt = reason.details as {
                  id?: string;
                  receipt?: string;
                };
                if (
                  typeof receipt?.id === "string" &&
                  typeof receipt?.receipt === "string"
                ) {
                  trackReceipt({ id: receipt.id, receipt: receipt.receipt });
                } else setError(reason);
              } else setError(reason);
            } finally {
              setPending(false);
            }
          }}
        >
          <h3>
            {scope === "account" ? "确认删除个人科研账户" : "确认删除原始文件"}
          </h3>
          <ul>
            {preview.effects.map((effect) => (
              <li key={effect}>{effect}</li>
            ))}
          </ul>
          <p>
            影响记录：{Object.values(preview.counts).reduce((a, b) => a + b, 0)}{" "}
            条（包括关联与历史记录）。
          </p>
          {scope === "file" && (
            <p>
              证据引用 {preview.counts.evidence} 条；活跃导出{" "}
              {preview.counts.active_exports} 个。
            </p>
          )}
          {scope === "account" && (
            <p>
              {preview.backup_retention_days
                ? `备份按 ${preview.backup_retention_days} 天保留期过期。`
                : "当前未配置备份保留期。本操作只能确认在线删除，不能确认备份已清除。"}
            </p>
          )}
          {preview.blocked ? (
            <p role="alert">
              存在依赖，不能执行此删除。保留引用来源并处理活跃导出后重新预览。
            </p>
          ) : (
            <>
              <label>
                输入登录密码以验证身份
                <input
                  autoComplete="current-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </label>
              <label>
                输入 DELETE 确认不可恢复的在线删除
                <input
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  required
                />
              </label>
              <Button
                disabled={pending || confirmation !== "DELETE" || !password}
                type="submit"
              >
                {pending ? "正在提交…" : "确认删除"}
              </Button>
            </>
          )}
          <Button
            type="button"
            variant="ghost"
            disabled={pending}
            onClick={() => {
              setPreview(undefined);
              setPassword("");
              setConfirmation("");
            }}
          >
            取消
          </Button>
        </form>
      )}
      {Boolean(error) && <ErrorBox error={error} />}
    </div>
  );
}
