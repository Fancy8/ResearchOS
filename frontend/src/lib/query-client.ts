// Adapted from Open Notebook query-client.ts (MIT); see THIRD_PARTY_NOTICES.md.
import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) =>
          !(
            error instanceof ApiError &&
            [401, 403, 404, 409, 422].includes(error.status)
          ) && count < 2,
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}

export const scopedKey = (
  workspace: string,
  resource: string,
  ...parts: unknown[]
) => ["workspace", workspace, resource, ...parts] as const;
