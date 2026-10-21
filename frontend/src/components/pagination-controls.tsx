"use client";
import type { PageState } from "@/lib/pagination";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";

export function PaginationControls({
  query,
  label,
}: {
  query: PageState;
  label: string;
}) {
  if (!query.data) return null;
  return (
    <div className="pagination-controls">
      {query.data.data.length > 0 && (
        <span className="muted">
          已显示 {query.data.data.length} 条
          {query.hasNextPage ? "，还有更多" : ""}
        </span>
      )}
      {Boolean(query.pageError || query.error) && (
        <ErrorBox
          error={query.pageError || query.error}
          retry={() => query.retryPage?.()}
        />
      )}
      {query.hasNextPage && (
        <Button
          type="button"
          variant="outline"
          aria-label={`加载更多${label}`}
          disabled={query.isFetching}
          onClick={() => query.fetchNextPage({ cancelRefetch: false })}
        >
          {query.isFetchingNextPage ? "正在加载…" : `加载更多${label}`}
        </Button>
      )}
    </div>
  );
}
