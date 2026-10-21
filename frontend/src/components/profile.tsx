"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write } from "@/lib/api";
import { scopedKey } from "@/lib/query-client";
import type { User, Project } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorBox, Heading, Loading } from "./common";

type Profile = {
  version: number;
  degree_stage: string | null;
  field_of_study: string | null;
  personalization_enabled: boolean;
  dashboard_preferences: Record<string, { pinned?: string[] }>;
};

export function ProfilePage({
  user,
  current,
}: {
  user: User;
  current?: Project;
}) {
  const cache = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [saved, setSaved] = useState(false);
  const [verificationMessage, setVerificationMessage] = useState("");
  const profile = useQuery({
    queryKey: scopedKey(user.workspace_id, "profile"),
    queryFn: () => api<Profile>("/research-profile"),
  });
  if (profile.isPending) return <Loading />;
  if (profile.error) return <ErrorBox error={profile.error} />;
  const value = profile.data.data;
  return (
    <>
      <Heading
        eyebrow="YOUR RESEARCH PROFILE"
        title="科研画像与偏好"
        text="背景帮助组织工作台。研究阶段始终由你在每个课题中明确选择。"
      />
      <section className="panel profile-card">
        <div className="email-verification">
          <p>
            账户邮箱：{user.email} ·{" "}
            {user.email_verified_at ? "已验证" : "待验证"}
          </p>
          {!user.email_verified_at && (
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                try {
                  const result = await write<{ message: string }>(
                    "/auth/email-verification-requests",
                    "POST",
                    {},
                  );
                  setVerificationMessage(result.data.message);
                } catch (reason) {
                  setError(reason);
                }
              }}
            >
              发送邮箱验证邮件
            </Button>
          )}
          {verificationMessage && <p role="status">{verificationMessage}</p>}
        </div>
        <form
          key={value.version}
          onSubmit={async (event) => {
            event.preventDefault();
            setError(undefined);
            const data = new FormData(event.currentTarget);
            try {
              await write("/research-profile", "PATCH", {
                expected_version: value.version,
                degree_stage: data.get("degree_stage") || null,
                field_of_study: data.get("field_of_study"),
                personalization_enabled: data.get("personalization") === "on",
                dashboard_preferences: {
                  ...value.dashboard_preferences,
                  ...(current
                    ? { [current.id]: { pinned: data.getAll("pinned") } }
                    : {}),
                },
              });
              await cache.invalidateQueries({
                queryKey: ["workspace", user.workspace_id],
              });
              setSaved(true);
            } catch (reason) {
              setError(reason);
            }
          }}
        >
          <label className="field">
            学历阶段
            <select name="degree_stage" defaultValue={value.degree_stage ?? ""}>
              <option value="">暂不设置</option>
              <option value="master">硕士</option>
              <option value="phd">博士</option>
              <option value="other">其他</option>
            </select>
          </label>
          <label className="field">
            研究领域
            <input
              name="field_of_study"
              defaultValue={value.field_of_study ?? ""}
            />
          </label>
          <label className="checkbox-line">
            <input
              type="checkbox"
              name="personalization"
              defaultChecked={value.personalization_enabled}
            />
            根据显式课题阶段调整首页模块顺序
          </label>
          {current && (
            <fieldset className="profile-pinned">
              <legend>为“{current.title}”固定优先模块</legend>
              {[
                ["threads", "研究问题"],
                ["tasks", "下一步行动"],
                ["activity", "近期活动"],
              ].map(([key, label]) => (
                <label className="checkbox-line" key={key}>
                  <input
                    type="checkbox"
                    name="pinned"
                    value={key}
                    defaultChecked={value.dashboard_preferences[
                      current.id
                    ]?.pinned?.includes(key)}
                  />
                  {label}
                </label>
              ))}
            </fieldset>
          )}
          {Boolean(error) && <ErrorBox error={error} />}
          <Button type="submit">保存偏好</Button>
          {saved && (
            <span className="saved-label" role="status">
              设置已保存
            </span>
          )}
        </form>
      </section>
    </>
  );
}
