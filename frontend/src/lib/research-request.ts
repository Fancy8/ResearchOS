import { api } from "./api";

// The server retains idempotency receipts for one day. Leave an hour of margin.
export const SAFE_REPLAY_AGE_MS = 23 * 60 * 60 * 1000;

export async function researchRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    return await api<T>(path, {
      method,
      signal: controller.signal,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      headers: key ? { "Idempotency-Key": key } : {},
    });
  } catch (error) {
    if (controller.signal.aborted)
      throw new Error("请求超时，结果尚未确认。请重试原请求或读取最新状态。");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
