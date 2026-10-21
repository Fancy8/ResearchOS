"use client";
import { useDeferredValue, useState } from "react";
import Link from "next/link";
import { BookOpen, ArrowUpRight } from "lucide-react";
import { ApiError } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import type { User, Project } from "@/lib/types";
import { Button } from "./ui/button";
import { Empty, ErrorBox, Heading, Loading } from "./common";
import { usePagedRows } from "@/lib/pagination";
import { PaginationControls } from "./pagination-controls";
import type { components } from "@/lib/generated-contracts";

export type Paper = components["PaperPublic"];
export { UploadButton } from "./upload-button";
import { UploadButton } from "./upload-button";

export function LibraryPage({
  user,
  current,
}: {
  user: User;
  current?: Project;
}) {
  const [keyword, setKeyword] = useState("");
  const query = useDeferredValue(keyword.trim());
  const rows = usePagedRows<Paper>({
    queryKey: scopedKey(user.workspace_id, "papers"),
    path: `/papers?q=${encodeURIComponent(query)}`,
    refetchInterval: 3000,
  });
  const filtered = rows.data?.data ?? [];
  return (
    <>
      <Heading
        eyebrow="RESEARCH LIBRARY"
        title="文献库"
        text="阅读只是起点。把重要原文转为与研究问题相关的证据。"
        action={<UploadButton user={user} current={current} />}
      />
      <section className="panel">
        <div className="library-toolbar">
          <span>
            <BookOpen size={16} />
            我的文献
          </span>
          <input
            aria-label="筛选文献标题"
            maxLength={100}
            placeholder="筛选标题关键词"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </div>
        {rows.isPending ? (
          <Loading />
        ) : rows.error ? (
          <ErrorBox error={rows.error} retry={() => rows.refetch()} />
        ) : filtered.length ? (
          <div className="table-scroll">
            <table className="library-table">
              <thead>
                <tr>
                  <th>文献</th>
                  <th>年份</th>
                  <th>阅读状态</th>
                  <th>文件状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((paper) => (
                  <tr key={paper.id}>
                    <td>
                      <Link href={`/papers/${paper.id}`}>{paper.title}</Link>
                      <small>
                        {paper.authors.join("、") || "元数据可手动编辑"}
                      </small>
                    </td>
                    <td>{paper.publication_year ?? "—"}</td>
                    <td>
                      {
                        { unread: "未读", reading: "阅读中", read: "已读" }[
                          paper.reading_status
                        ]
                      }
                    </td>
                    <td>
                      <span
                        className={`badge status-${paper.file?.parse_status}`}
                      >
                        {!paper.file
                          ? "暂无 PDF"
                          : paper.file.availability_status !== "available"
                            ? "原件不可用"
                            : paper.file.upload_status === "failed"
                              ? "上传验证失败"
                              : paper.file.parse_status === "ready"
                                ? `${paper.file.page_count} 页${paper.file.has_text_layer === false ? " · 扫描件" : ""}`
                                : paper.file.parse_status === "failed"
                                  ? "解析失败"
                                  : "后台处理中"}
                      </span>
                    </td>
                    <td>
                      <Link
                        aria-label={`打开 ${paper.title}`}
                        href={`/papers/${paper.id}`}
                      >
                        <ArrowUpRight size={16} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={keyword ? "没有匹配文献" : "把第一篇论文放进研究空间"}
            text="支持有文本层的 PDF 和扫描件。扫描件可阅读并添加页码级证据。"
          />
        )}
        <PaginationControls query={rows} label="文献" />
      </section>
    </>
  );
}
