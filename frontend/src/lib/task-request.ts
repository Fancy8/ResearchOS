import { researchRequest } from "./research-request";
import type { Task } from "./types";

export function taskRequest(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
) {
  return researchRequest<Task>(path, method, body, key);
}
