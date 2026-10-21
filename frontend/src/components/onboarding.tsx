"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import { stages, type User } from "@/lib/types";
import { ErrorBox, FormDialog, Heading, Loading } from "./common";
import type { components } from "@/lib/generated-contracts";

type State = components["OnboardingPublic"];
export function OnboardingPage({ user }: { user: User }) {
  const state = useQuery({
    queryKey: scopedKey(user.workspace_id, "onboarding"),
    queryFn: () => api<State>("/onboarding"),
  });
  if (state.isPending) return <Loading />;
  if (state.error) return <ErrorBox error={state.error} />;
  return <OnboardingForm user={user} initial={state.data.data} />;
}
function OnboardingForm({ user, initial }: { user: User; initial: State }) {
  const router = useRouter();
  const cache = useQueryClient();
  const version = useRef(initial.draft_version ?? 0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const inFlight = useRef<Promise<void>>(Promise.resolve());
  const localKey = `researchos.${user.workspace_id}.onboarding`;
  const [status, setStatus] = useState("首次设置草稿会自动保存");
  const [draft] = useState(() => {
    try {
      return (
        JSON.parse(localStorage.getItem(localKey) ?? "null") ??
        initial.draft ??
        {}
      );
    } catch {
      return initial.draft ?? {};
    }
  });
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <>
      <Heading
        eyebrow="START YOUR RESEARCH"
        title="从你的第一个研究问题开始"
        text="研究领域和阶段可以随时调整。不需要上传论文，也能开始。"
      />
      <section className="panel onboarding-card">
        <h2>给研究一个明确的起点</h2>
        <p>先创建课题，再提出一个你想持续推进的问题。</p>
        <p role="status">{status}</p>
        <FormDialog
          title="创建首个课题与研究线索"
          trigger={<span className="primary-trigger">+ 开始设置</span>}
          fields={[
            {
              name: "project_title",
              label: "课题名称",
              default: draft.project_title,
            },
            {
              name: "question",
              label: "首个研究问题",
              type: "textarea",
              default: draft.question,
            },
            {
              name: "research_stage",
              label: "研究阶段",
              type: "select",
              options: stages,
              default: draft.research_stage,
            },
            {
              name: "field_of_study",
              label: "研究领域",
              required: false,
              default: draft.field_of_study,
            },
          ]}
          onFormChange={(values) => {
            try {
              localStorage.setItem(localKey, JSON.stringify(values));
            } catch {
              setStatus("本机草稿暂存不可用，请确认服务器保存成功");
            }
            setStatus("保存草稿中…");
            if (timer.current) clearTimeout(timer.current);
            timer.current = setTimeout(() => {
              inFlight.current = inFlight.current.then(async () => {
                try {
                  const result = await write<State>(
                    "/onboarding/draft",
                    "PUT",
                    { ...values, expected_draft_version: version.current },
                  );
                  version.current = result.data.draft_version!;
                  cache.setQueryData(
                    scopedKey(user.workspace_id, "onboarding"),
                    result,
                  );
                  setStatus("草稿已保存，可随时继续");
                } catch {
                  setStatus("草稿保留在此浏览器，服务器保存失败或发生版本冲突");
                }
              });
            }, 700);
          }}
          onSubmit={async (values) => {
            if (timer.current) clearTimeout(timer.current);
            await inFlight.current;
            await write("/onboarding", "PUT", values, crypto.randomUUID());
            localStorage.removeItem(localKey);
            await cache.invalidateQueries({
              queryKey: ["workspace", user.workspace_id],
            });
            await cache.invalidateQueries({ queryKey: ["identity"] });
            router.push("/dashboard");
          }}
        />
      </section>
    </>
  );
}
