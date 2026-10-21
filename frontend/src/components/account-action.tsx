"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { write } from "@/lib/api";
import { Button } from "./ui/button";
import { ErrorBox } from "./common";

export function AccountAction() {
  const action =
    useSearchParams().get("action") === "reset" ? "reset" : "verify";
  const [token, setToken] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const cache = useQueryClient();
  useEffect(() => {
    const fragmentToken = new URLSearchParams(
      window.location.hash.slice(1),
    ).get("token");
    if (fragmentToken) setToken(fragmentToken);
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
  }, []);
  return (
    <main className="deletion-status panel">
      <div className="eyebrow">RESEARCHOS · ACCOUNT</div>
      <h1>{action === "reset" ? "重置登录密码" : "验证账户邮箱"}</h1>
      {message ? (
        <p role="status">{message}</p>
      ) : (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setPending(true);
            setError(undefined);
            try {
              const result = await write<{ message: string }>(
                action === "reset"
                  ? "/auth/reset-password"
                  : "/auth/verify-email",
                "POST",
                {
                  token,
                  ...(action === "reset"
                    ? { password: form.get("password") }
                    : {}),
                },
              );
              setMessage(result.data.message);
              setToken("");
              cache.clear();
            } catch (reason) {
              setError(reason);
            } finally {
              setPending(false);
            }
          }}
        >
          <p>请确认由你本人发起此操作。链接只能使用一次。</p>
          <label>
            邮件中的验证令牌
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
              autoComplete="off"
            />
          </label>
          {action === "reset" && (
            <label>
              新密码（至少 12 字符）
              <input
                type="password"
                name="password"
                minLength={12}
                maxLength={128}
                required
                autoComplete="new-password"
              />
            </label>
          )}
          <Button disabled={pending || !token} type="submit">
            {pending
              ? "正在处理…"
              : action === "reset"
                ? "确认重置密码"
                : "确认验证邮箱"}
          </Button>
        </form>
      )}
      {Boolean(error) && <ErrorBox error={error} />}
      <p>
        <Link href="/login">返回登录页</Link>
      </p>
    </main>
  );
}
