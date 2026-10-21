"use client";
import { useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Upload } from "lucide-react";
import { useUpload, type UploadResult } from "@/lib/use-upload";
import type { User, Project } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";

const parseNames: Record<string, string> = {
  pending: "等待上传",
  queued: "等待解析",
  processing: "解析中",
  ready: "解析完成",
  failed: "解析失败",
};
const uploadNames: Record<string, string> = {
  pending: "等待确认",
  validating: "后台验证中",
  completed: "原件已接收",
  failed: "上传失败",
  expired: "上传已过期",
};

export function UploadButton({
  user,
  current,
  paperId,
  onFinish,
}: {
  user: User;
  current?: Project;
  paperId?: string;
  onFinish?: (result: UploadResult) => void | Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const upload = useUpload(user.workspace_id, { current, paperId, onFinish });
  const record = upload.record;
  const recovering = record && !["accepted", "terminal"].includes(record.phase);
  return (
    <section className="upload-control" aria-label="PDF 上传与恢复">
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        aria-label="选择 PDF 文件"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          if (file) await upload.choose(file);
          if (input.current) input.current.value = "";
        }}
      />
      <Button
        type="button"
        onClick={() => input.current?.click()}
        disabled={!upload.loaded || upload.pending || upload.storageBlocked}
      >
        <Upload size={16} />
        {recovering ? "选择原 PDF 继续" : paperId ? "上传新版本" : "上传 PDF"}
      </Button>
      {record && (
        <div className="upload-feedback">
          <p>
            原文件：{record.name} · {record.projectTitle}
            {record.paperId ? " · 已有文献的新版本" : " · 新文献"}
          </p>
          {recovering && (
            <>
              <p>
                恢复将继续处理上方原文件与课题；切换当前课题不会改变此次上传。
              </p>
              <Button
                type="button"
                variant="outline"
                disabled={upload.pending || upload.storageBlocked}
                onClick={() => upload.resume()}
              >
                {record.phase === "duplicates"
                  ? "读取相同文件记录"
                  : "继续原上传"}
              </Button>
              {!upload.hasFile &&
                ["preflight", "init", "transfer"].includes(record.phase) && (
                  <p>请重新选择原 PDF 以便继续传输。</p>
                )}
            </>
          )}
          {record.phase === "duplicates" && (
            <div aria-label="相同文件选择">
              <p>已有相同文件。请选择复用确切版本，或明确保留一条独立记录。</p>
              {upload.duplicates.map((candidate) => (
                <div key={candidate.paper_file_id}>
                  <span>
                    {candidate.title} · v{candidate.version_no}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={upload.pending}
                    onClick={async () => {
                      const href = await upload.reuse(candidate);
                      if (href) router.push(href);
                    }}
                  >
                    复用此版本
                  </Button>
                </div>
              ))}
              {upload.cursor && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={upload.pending}
                  onClick={() => upload.more()}
                >
                  加载更多相同文件
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                disabled={upload.pending || upload.storageBlocked}
                onClick={() => upload.independentCopy()}
              >
                仍上传独立记录
              </Button>
            </div>
          )}
          {record.phase === "accepted" && (
            <p role="status">后台验证与解析已接收</p>
          )}
          {record.phase === "terminal" && (
            <p role="status">
              {record.terminalReason === "expired"
                ? "原上传已过期"
                : "原上传无法继续"}
              。可核对原文件后重新选择 PDF，发起一次明确的新上传。
            </p>
          )}
          {record.initialized && (
            <div>
              <Link
                href={`/papers/${record.initialized.paper_id}?fileId=${record.initialized.paper_file_id}`}
              >
                查看原文件版本
              </Link>
              <Button
                type="button"
                variant="outline"
                disabled={upload.pending}
                onClick={() => upload.inspect()}
              >
                读取上传状态
              </Button>
            </div>
          )}
          {upload.snapshot && (
            <p role="status">
              上传：
              {uploadNames[upload.snapshot.upload.status] ??
                upload.snapshot.upload.status}
              ；解析：
              {parseNames[upload.snapshot.parse.parse_status] ??
                upload.snapshot.parse.parse_status}
              。后台处理结果以文件状态为准。
            </p>
          )}
        </div>
      )}
      {upload.pending && (
        <div className="upload-feedback" role="status">
          {upload.working}
          {upload.progress !== null && ` ${upload.progress}%`}
          {upload.progress !== null && (
            <Button type="button" variant="outline" onClick={upload.pause}>
              暂停传输
            </Button>
          )}
        </div>
      )}
      {Boolean(upload.error) && <ErrorBox error={upload.error} />}
      {Boolean(upload.refreshError) && (
        <div>
          <p>请求已接收，刷新或本地记录暂未完成。请读取原文件状态。</p>
          <ErrorBox error={upload.refreshError} />
        </div>
      )}
      {upload.storageBlocked && (
        <Button
          type="button"
          variant="outline"
          disabled={upload.pending}
          onClick={() => upload.retryRead()}
        >
          重新读取恢复记录
        </Button>
      )}
      {(record || upload.storageBlocked) && (
        <details>
          <summary>管理本机恢复记录</summary>
          <p>
            请先在文献库核对处理结果。清除记录不会取消后台任务、删除文件或释放上传配额。
          </p>
          <Link href="/library">核对文献库</Link>
          <Button
            type="button"
            variant="outline"
            disabled={upload.pending}
            onClick={() => upload.forget()}
          >
            已核对，清除本机恢复记录
          </Button>
        </details>
      )}
    </section>
  );
}
