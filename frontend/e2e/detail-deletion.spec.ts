import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";

async function account(page: Page) {
  const root = path.resolve(process.cwd(), "..");
  const email = `details-${Date.now()}@example.com`;
  const invitation = execFileSync(
    path.join(root, "runtime/venv/Scripts/python.exe"),
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  const origin = { Origin: "http://localhost:3000" };
  const registration = await page.request.post("/api/v1/auth/register", {
    headers: origin,
    data: {
      email,
      password: "ResearchOS-browser-2026",
      display_name: "详情测试",
      invitation_token: invitation,
    },
  });
  expect(registration.status()).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-browser-2026" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    ...origin,
    "X-CSRF-Token": (await login.json()).data.csrf_token,
    "Idempotency-Key": crypto.randomUUID(),
  };
  const onboarding = await page.request.put("/api/v1/onboarding", {
    headers,
    data: {
      project_title: "详情验收课题",
      question: "细化任务是否保留来源？",
      research_stage: "experimentation",
    },
  });
  expect(onboarding.status()).toBe(200);
  return headers;
}

test("precise task detail edit, search jump and immutable decision provenance", async ({
  page,
}) => {
  const headers = await account(page);
  const projects = (await (await page.request.get("/api/v1/projects")).json())
    .data;
  const threads = (
    await (
      await page.request.get(`/api/v1/projects/${projects[0].id}/threads`)
    ).json()
  ).data;
  const decision = (
    await (
      await page.request.post(`/api/v1/threads/${threads[0].id}/decisions`, {
        headers,
        data: {
          title: "详情决策",
          reason: "需要明确原始依据",
          decision_type: "adopt",
        },
      })
    ).json()
  ).data;
  const task = (
    await (
      await page.request.post("/api/v1/tasks", {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
        data: {
          title: "详情任务",
          project_id: projects[0].id,
          thread_id: threads[0].id,
          decision_id: decision.id,
        },
      })
    ).json()
  ).data;
  await page.goto(`/tasks/${task.id}`);
  await page.getByRole("button", { name: "编辑任务", exact: true }).click();
  await page.getByLabel("任务名称").fill("详情任务已编辑");
  await page.getByLabel("任务状态").selectOption("blocked");
  await page.getByLabel("优先级").selectOption("high");
  await page.getByLabel("截止日期").fill("2026-11-20");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "详情任务已编辑" }),
  ).toBeVisible();
  await expect(page.getByText("2026-11-20", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "查看任务产生时的决策 v1" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/decisions/${decision.id}\\?revision=1`),
  );
  await expect(page.getByRole("heading", { name: "详情决策" })).toBeVisible();
  const note = await page.request.post("/api/v1/notes", {
    headers,
    data: { title: "新的笔记依据" },
  });
  expect(note.status()).toBe(201);
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  await page.getByLabel("新的决策理由").fill("加入笔记后的完整新理由");
  await page
    .getByRole("checkbox", { name: "新的笔记依据", exact: true })
    .check();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByLabel("决策版本", { exact: true }).selectOption("2");
  await expect(
    page
      .locator(".decision-reason")
      .getByText("加入笔记后的完整新理由", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  await page.getByLabel("新的决策理由").fill("冲突后仍须保留的表单输入");
  const external = await page.request.post(
    `/api/v1/decisions/${decision.id}/revisions`,
    {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: {
        expected_revision: 2,
        title: "详情决策",
        decision_type: "adjust",
        reason: "另一个页面的最新判断",
      },
    },
  );
  expect(external.status()).toBe(201);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "服务器已保存决策 v3" }),
  ).toBeVisible();
  await expect(page.getByLabel("新的决策理由")).toHaveValue(
    "冲突后仍须保留的表单输入",
  );
  await page
    .getByRole("button", { name: "采用服务器最新版本作为修订基准" })
    .click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByLabel("决策版本", { exact: true }).selectOption("4");
  await expect(
    page
      .locator(".decision-reason")
      .getByText("冲突后仍须保留的表单输入", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("决策版本", { exact: true }).selectOption("1");
  await expect(
    page.getByText("需要明确原始依据", { exact: true }),
  ).toBeVisible();
  await page.goto("/search?q=详情任务已编辑");
  await page.getByRole("link").filter({ hasText: "详情任务已编辑" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${task.id}$`));
});

for (const pendingJournalResponse of [false, true]) {
  test(`account deletion preview, reauthentication, live worker and revoked login${pendingJournalResponse ? " with a pending journal receipt" : ""}`, async ({
    page,
  }) => {
    await account(page);
    if (pendingJournalResponse) {
      await page.route("**/api/v1/deletions", async (route) => {
        const original = await route.fetch();
        expect(original.status()).toBe(202);
        const job = (await original.json()).data;
        await route.fulfill({
          response: original,
          status: 503,
          json: {
            error: {
              code: "DELETION_JOURNAL_PENDING",
              message: "删除已排队，独立日志尚待确认",
              details: { id: job.id, receipt: job.receipt, scope: job.scope },
            },
            request_id: "browser-pending-journal-probe",
          },
        });
      });
    }
    await page.goto("/settings/data");
    await page.getByRole("button", { name: "预览账户删除影响" }).click();
    await expect(
      page.getByRole("heading", { name: "确认删除个人科研账户" }),
    ).toBeVisible();
    await page
      .getByLabel("输入登录密码以验证身份")
      .fill("ResearchOS-browser-2026");
    await page.getByLabel("输入 DELETE 确认不可恢复的在线删除").fill("DELETE");
    await page.getByRole("button", { name: "确认删除", exact: true }).click();
    await expect(page).toHaveURL(/deletion-status\?id=/);
    await expect(
      page.getByRole("heading", { name: "在线删除已完成", exact: true }),
    ).toBeVisible({ timeout: 20000 });
    expect((await page.request.get("/api/v1/me")).status()).toBe(401);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "在线删除已完成", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: "../artifacts/account-deletion.png",
      fullPage: true,
    });
  });
}

test("verification and password recovery through real mail queue and one-time browser links", async ({
  page,
}) => {
  await account(page);
  const identity = (await (await page.request.get("/api/v1/me")).json()).data;
  const folder = path.resolve(
    process.cwd(),
    `../runtime/mail-preview/researchos/development/${identity.workspace_id}`,
  );
  function mailLink(action: string) {
    if (!fs.existsSync(folder)) return "";
    for (const file of fs
      .readdirSync(folder)
      .filter((value) => value.endsWith(".eml"))) {
      const raw = fs.readFileSync(path.join(folder, file), "utf-8");
      const body = raw
        .split(/\r?\n\r?\n/)
        .slice(1)
        .join("\n\n");
      const content = /Content-Transfer-Encoding:\s*base64/i.test(raw)
        ? Buffer.from(body.replace(/\s/g, ""), "base64").toString("utf-8")
        : body.replace(/=\r?\n/g, "").replace(/=3D/g, "=");
      const link =
        content.match(
          /http:\/\/localhost:3000\/account-action\?action=[^\s]+/,
        )?.[0] ?? "";
      if (link.includes(`action=${action}#`)) return link;
    }
    return "";
  }
  await expect.poll(() => mailLink("verify"), { timeout: 15000 }).not.toBe("");
  await page.goto(mailLink("verify"));
  await page.getByRole("button", { name: "确认验证邮箱", exact: true }).click();
  await expect(
    page.getByText("邮箱验证已完成。", { exact: true }),
  ).toBeVisible();
  expect(
    (await (await page.request.get("/api/v1/me")).json()).data
      .email_verified_at,
  ).toBeTruthy();
  await page.goto("/login");
  await page.getByRole("button", { name: "忘记密码？", exact: true }).click();
  await page.getByLabel("需要找回的账户邮箱").fill(identity.email);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(() => mailLink("reset"), { timeout: 15000 }).not.toBe("");
  await page.goto(mailLink("reset"));
  await page
    .getByLabel("新密码（至少 12 字符）")
    .fill("ResearchOS-recovered-2026");
  await page.getByRole("button", { name: "确认重置密码", exact: true }).click();
  await expect(
    page.getByText("密码已重置，原登录会话已撤销。请使用新密码登录。", {
      exact: true,
    }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/me")).status()).toBe(401);
  await page.getByRole("link", { name: "返回登录页" }).click();
  await page.getByLabel("邮箱", { exact: true }).fill(identity.email);
  await page
    .getByLabel("密码", { exact: true })
    .fill("ResearchOS-recovered-2026");
  await page.getByRole("button", { name: "登录科研空间", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "详情验收课题", exact: true }),
  ).toBeVisible();
});
