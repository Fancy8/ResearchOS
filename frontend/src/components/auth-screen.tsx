"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ArrowRight, BookOpen, GitBranch, ShieldCheck } from "lucide-react";
import { write } from "@/lib/api";
import { Button } from "./ui/button";
import { ErrorBox, FormDialog } from "./common";

export function AuthScreen() {
  const [register, setRegister] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [recoveryMessage, setRecoveryMessage] = useState("");
  const client = useQueryClient();
  const router = useRouter();
  return (
    <main className="auth-layout">
      <section className="auth-story">
        <div className="brand">
          <GitBranch />
          ResearchOS<span>个人科研空间</span>
        </div>
        <div className="story-body">
          <div className="eyebrow">ONE RESEARCHER, ONE RESEARCHOS</div>
          <h1>
            让每一次思考，
            <br />
            都有迹可循。
          </h1>
          <p>
            从一段论文原文，到一个研究判断，
            <br />
            再到下一步值得开展的行动。
          </p>
          <div className="research-chain">
            <span>研究问题</span>
            <ArrowRight />
            <span>原文证据</span>
            <ArrowRight />
            <span>研究行动</span>
          </div>
        </div>
        <div className="auth-foot">
          <ShieldCheck size={17} /> 私有科研资料 · 保留原始依据 · 可导出归档
        </div>
      </section>
      <section className="auth-form">
        <div className="auth-card">
          <BookOpen className="auth-icon" />
          <h2>{register ? "创建你的科研空间" : "回到你的研究"}</h2>
          <p>
            {register
              ? "使用邀请邮箱，开始积累真实研究记录。"
              : "登录后继续你的研究线索与下一步行动。"}
          </p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const values = Object.fromEntries(
                new FormData(event.currentTarget),
              );
              setPending(true);
              setError(undefined);
              try {
                if (register) await write("/auth/register", "POST", values);
                await write("/auth/login", "POST", {
                  email: values.email,
                  password: values.password,
                });
                await client.invalidateQueries({ queryKey: ["identity"] });
                router.push(register ? "/onboarding" : "/dashboard");
              } catch (reason) {
                setError(reason);
              } finally {
                setPending(false);
              }
            }}
          >
            {register && (
              <label className="field">
                你的称呼
                <input name="display_name" required autoComplete="name" />
              </label>
            )}
            <label className="field">
              邮箱
              <input
                type="email"
                name="email"
                required
                autoComplete="email"
                placeholder="you@university.edu"
              />
            </label>
            <label className="field">
              密码
              <input
                type="password"
                name="password"
                required
                minLength={register ? 12 : 1}
                autoComplete={register ? "new-password" : "current-password"}
              />
            </label>
            {register && (
              <label className="field">
                邀请码
                <input name="invitation_token" required autoComplete="off" />
              </label>
            )}
            {Boolean(error) && <ErrorBox error={error} />}
            <Button type="submit" className="wide-button" disabled={pending}>
              {pending ? "正在处理…" : register ? "创建空间" : "登录科研空间"}
              <ArrowRight size={16} />
            </Button>
          </form>
          <button
            className="text-button auth-switch"
            onClick={() => {
              setRegister(!register);
              setError(undefined);
            }}
          >
            {register ? "已有账号？登录" : "有邀请码？创建账号"}
          </button>
          {!register && (
            <FormDialog
              title="找回登录密码"
              trigger={<span className="text-button">忘记密码？</span>}
              fields={[
                { name: "email", label: "需要找回的账户邮箱", type: "email" },
              ]}
              onSubmit={async (values) => {
                const result = await write<{ message: string }>(
                  "/auth/password-reset-requests",
                  "POST",
                  values,
                );
                setRecoveryMessage(result.data.message);
              }}
            />
          )}
          {recoveryMessage && <p role="status">{recoveryMessage}</p>}
        </div>
      </section>
    </main>
  );
}
