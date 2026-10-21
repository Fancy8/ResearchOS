"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import "./pdf-text-layer.css";
import { api, write } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import type { User, Project, Thread } from "@/lib/types";
import { useEvidenceDraft, type Evidence } from "@/lib/evidence-draft";
import { usePagedRows } from "@/lib/pagination";
import type { Paper } from "./library";
import { UploadButton } from "./library";
import { Button } from "./ui/button";
import { ErrorBox, Loading } from "./common";
import { PaperManagement } from "./paper-management";
import { EvidenceEditor } from "./evidence-editor";
import { PdfPage, type FileAddress, type RenderedPage } from "./pdf-page";

function pageValue(value: string | null) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : 1;
}

export function PdfReader({
  user,
  current,
  identifier,
}: {
  user: User;
  current?: Project;
  identifier: string;
}) {
  const params = useSearchParams();
  const cache = useQueryClient();
  const sourceId = params.get("evidenceId");
  const requestedFile = params.get("fileId");
  const requestedPage = params.get("page");
  const [pageNumber, setPageNumber] = useState(pageValue(requestedPage));
  const [scale, setScale] = useState(1);
  const [rendered, setRendered] = useState<RenderedPage>();
  const [highlightStatus, setHighlightStatus] = useState("正在校验显示位置");
  const draft = useEvidenceDraft(user.workspace_id);
  const paper = useQuery({
    queryKey: scopedKey(user.workspace_id, "paper", identifier),
    queryFn: () => api<Paper>(`/papers/${identifier}`),
  });
  const address = useQuery({
    queryKey: scopedKey(
      user.workspace_id,
      "paper-file",
      identifier,
      requestedFile,
    ),
    queryFn: () =>
      api<FileAddress>(
        `/papers/${identifier}/file${requestedFile ? `?file_id=${requestedFile}` : ""}`,
      ),
    retry: false,
    refetchInterval: (query) => (query.state.data ? false : 2000),
  });
  const lines = usePagedRows<Thread>({
    queryKey: scopedKey(user.workspace_id, "reader-threads", current?.id),
    path: `/projects/${current?.id}/threads`,
    enabled: !!current,
  });
  const source = useQuery({
    queryKey: scopedKey(user.workspace_id, "source-evidence", sourceId),
    queryFn: () => api<Evidence>(`/evidence/${sourceId}`),
    enabled: !!sourceId,
  });
  const file = address.data?.data;
  useEffect(() => {
    setPageNumber(pageValue(requestedPage));
  }, [requestedFile, requestedPage, file?.paper_file_id]);
  const page = Math.max(1, Math.min(file?.page_count ?? 1, pageNumber));
  const view =
    file &&
    !address.error &&
    rendered?.fileId === file.paper_file_id &&
    rendered.page === page &&
    rendered.scale === scale
      ? rendered
      : undefined;
  return (
    <>
      <div className="reader-top">
        <Link href="/library" className="breadcrumb">
          <ArrowLeft size={16} /> 返回文献库
        </Link>
        <h1>{paper.data?.data.title ?? "PDF 阅读器"}</h1>
        <UploadButton
          user={user}
          current={current}
          paperId={identifier}
          onFinish={() =>
            cache.invalidateQueries({
              queryKey: scopedKey(user.workspace_id, "paper-file", identifier),
            })
          }
        />
      </div>
      <PaperManagement user={user} identifier={identifier} />
      {file && (
        <div className="reader-toolbar">
          <span className="badge">
            文件 v{file.version_no}
            {!file.is_current && " · 历史版本"}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="上一页"
            disabled={page === 1}
            onClick={() => setPageNumber(page - 1)}
          >
            <ChevronLeft size={17} />
          </Button>
          <label>
            第{" "}
            <input
              aria-label="PDF 页码"
              type="number"
              min={1}
              max={file.page_count}
              value={page}
              onChange={(event) => setPageNumber(pageValue(event.target.value))}
            />{" "}
            / {file.page_count} 页
          </label>
          <Button
            variant="ghost"
            size="icon"
            aria-label="下一页"
            disabled={page === file.page_count}
            onClick={() => setPageNumber(page + 1)}
          >
            <ChevronRight size={17} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="缩小"
            onClick={() => setScale(Math.max(0.5, scale - 0.25))}
          >
            <ZoomOut size={17} />
          </Button>
          <span>{Math.round(scale * 100)}%</span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="放大"
            onClick={() => setScale(Math.min(2, scale + 0.25))}
          >
            <ZoomIn size={17} />
          </Button>
          <select
            aria-label="阅读状态"
            value={paper.data?.data.reading_status ?? "unread"}
            onChange={async (event) => {
              await write(`/papers/${identifier}`, "PATCH", {
                expected_version: paper.data?.data.version,
                reading_status: event.target.value,
              });
              void cache.invalidateQueries({
                queryKey: scopedKey(user.workspace_id, "paper", identifier),
              });
            }}
          >
            <option value="unread">未读</option>
            <option value="reading">阅读中</option>
            <option value="read">已读</option>
          </select>
        </div>
      )}
      <div className="reader-layout">
        <div className="pdf-scroll">
          {address.isPending ? (
            <Loading />
          ) : address.error ? (
            <ErrorBox error={address.error} retry={() => address.refetch()} />
          ) : (
            file && (
              <PdfPage
                key={`${file.paper_file_id}:${file.url}`}
                paperId={identifier}
                file={file}
                pageNumber={page}
                scale={scale}
                source={source.data?.data}
                onReady={setRendered}
                onHighlightStatus={setHighlightStatus}
                onSelection={draft.capture}
              />
            )
          )}
        </div>
        <div>
          {Boolean(source.error) && (
            <ErrorBox error={source.error} retry={() => source.refetch()} />
          )}
          <EvidenceEditor
            action={draft}
            view={view}
            lines={lines}
            source={source.data?.data}
            highlightStatus={highlightStatus}
          />
        </div>
      </div>
    </>
  );
}
