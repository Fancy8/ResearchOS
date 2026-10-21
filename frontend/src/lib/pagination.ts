"use client";
import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "./api";

export function usePagedRows<T extends { id: string }>({
  queryKey,
  path,
  enabled = true,
  refetchInterval = false,
}: {
  queryKey: readonly unknown[];
  path: string;
  enabled?: boolean;
  refetchInterval?: number | false | ((rows: T[]) => number | false);
}) {
  const query = useInfiniteQuery({
    queryKey: [...queryKey, "paged", path],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api<T[]>(
        `${path}${path.includes("?") ? "&" : "?"}limit=20${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
        { signal },
      ),
    getNextPageParam: (last) => last.meta?.next_cursor ?? undefined,
    enabled,
    refetchInterval:
      typeof refetchInterval === "function"
        ? (query) =>
            refetchInterval(
              query.state.data?.pages.flatMap((page) => page.data) ?? [],
            )
        : refetchInterval,
  });
  const seen = new Set<string>();
  const data = {
    data: (query.data?.pages.flatMap((page) => page.data) ?? []).filter(
      (row) => {
        if (seen.has(row.id)) return false;
        seen.add(row.id);
        return true;
      },
    ),
    meta: query.data?.pages.at(-1)?.meta,
  };
  return {
    ...query,
    data,
    error: query.data ? null : query.error,
    pageError: query.data ? query.error : null,
    retryPage: () =>
      query.isFetchNextPageError
        ? query.fetchNextPage({ cancelRefetch: false })
        : query.refetch(),
  };
}

export type PageState = {
  data?: { data: unknown[] };
  hasNextPage: boolean;
  isFetching: boolean;
  isFetchingNextPage: boolean;
  pageError: unknown;
  error?: unknown;
  retryPage?: () => Promise<unknown>;
  fetchNextPage: (options?: { cancelRefetch?: boolean }) => Promise<unknown>;
};
