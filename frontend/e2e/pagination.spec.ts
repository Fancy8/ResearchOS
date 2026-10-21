import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function account(page: Page) {
  const root = path.resolve(process.cwd(), "..");
  const email = `paging-${Date.now()}@example.com`;
  const invitation = execFileSync(
    path.join(root, "runtime/venv/Scripts/python.exe"),
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  const origin = { Origin: "http://localhost:3000" };
  const register = await page.request.post("/api/v1/auth/register", {
    headers: origin,
    data: {
      email,
      password: "ResearchOS-paging-2026",
      display_name: "分页研究者",
      invitation_token: invitation,
    },
  });
  expect(register.status()).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-paging-2026" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    ...origin,
    "X-CSRF-Token": (await login.json()).data.csrf_token,
  };
  const onboarding = await page.request.put("/api/v1/onboarding", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      project_title: "后页默认课题",
      question: "后页研究问题",
      research_stage: "experimentation",
    },
  });
  expect(onboarding.status()).toBe(200);
  const project = (
    await (await page.request.get("/api/v1/projects/current")).json()
  ).data;
  const thread = (
    await (
      await page.request.get(`/api/v1/projects/${project.id}/threads`)
    ).json()
  ).data[0];
  async function create(endpoint: string, data: object) {
    const result = await page.request.post(`/api/v1${endpoint}`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data,
    });
    expect(result.status()).toBe(201);
    return (await result.json()).data;
  }
  return { headers, project, thread, create };
}

test("paged library preserves rows after failure, searches older titles and resolves an older default project", async ({
  page,
}) => {
  test.setTimeout(90000);
  const { project, create } = await account(page);
  const oldest = await create("/papers", { title: "后页独有 100%_中文" });
  for (let index = 0; index < 25; index++) {
    await create("/papers", { title: `新文献 ${index}` });
    await create("/projects", { title: `新课题 ${index}` });
  }
  await page.goto("/library");
  await expect(page.getByLabel("切换当前课题")).toHaveValue(project.id);
  await expect(page.locator(".library-table tbody tr")).toHaveCount(20);
  await expect(
    page.getByRole("link", { name: oldest.title, exact: true }),
  ).toHaveCount(0);
  let fail = true;
  await page.route("**/api/v1/papers?**", async (route) => {
    if (new URL(route.request().url()).searchParams.has("cursor") && fail) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "TEST_PAGE_FAILURE", message: "后页暂时不可用" },
        }),
      });
    } else await route.continue();
  });
  await page.getByRole("button", { name: "加载更多文献", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "后页暂时不可用" }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".library-table tbody tr")).toHaveCount(20);
  fail = false;
  await page
    .getByRole("alert")
    .getByRole("button", { name: "重试", exact: true })
    .click();
  await expect(page.locator(".library-table tbody tr")).toHaveCount(26);
  await expect(
    page.getByRole("link", { name: oldest.title, exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator(".library-table tbody tr")).toHaveCount(20);
  await page.getByLabel("筛选文献标题").fill("100%_中文");
  await expect(page.locator(".library-table tbody tr")).toHaveCount(1);
  await expect(
    page.getByRole("link", { name: oldest.title, exact: true }),
  ).toBeVisible();
  await page.goto("/projects");
  await expect(page.locator(".project-card")).toHaveCount(20);
  await page.getByRole("button", { name: "加载更多课题", exact: true }).click();
  await expect(page.locator(".project-card")).toHaveCount(26);
  await expect(
    page.getByRole("heading", { name: project.title, exact: true }),
  ).toBeVisible();
});

test("older decision and question history plus later-page note association remain accessible", async ({
  page,
}) => {
  test.setTimeout(90000);
  const { headers, project, thread, create } = await account(page);
  const oldPaper = await create("/papers", { title: "后页关联目标文献" });
  const note = await create("/notes", { title: "分页关联笔记" });
  const decision = await create(`/threads/${thread.id}/decisions`, {
    title: "原始决策",
    reason: "原始理由",
    decision_type: "adopt",
  });
  const hypothesisIds: string[] = [];
  for (let index = 0; index < 24; index++) {
    await create("/papers", { title: `候选文献${index}` });
    hypothesisIds.push(
      (
        await create(`/threads/${thread.id}/hypotheses`, {
          statement: `分页候选假设${index}`,
        })
      ).id,
    );
    const updated = await page.request.patch(`/api/v1/threads/${thread.id}`, {
      headers,
      data: { expected_version: index + 1, question: `更新问题${index + 2}` },
    });
    expect(updated.status()).toBe(200);
    await create(`/decisions/${decision.id}/revisions`, {
      expected_revision: index + 1,
      title: "修订决策",
      reason: `修订理由${index + 2}`,
      decision_type: "adjust",
    });
  }
  await page.goto(`/notes/${note.id}`);
  await page.getByRole("button", { name: "关联文献", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("选择文献").locator("option")).toHaveCount(20);
  await dialog
    .getByRole("button", { name: "加载更多可关联文献", exact: true })
    .click();
  await expect(dialog.getByLabel("选择文献").locator("option")).toHaveCount(25);
  await dialog.getByLabel("选择文献").selectOption(oldPaper.id);
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page
      .locator(".note-associations")
      .getByRole("link", { name: oldPaper.title }),
  ).toBeVisible();
  await page.goto(`/threads/${thread.id}`);
  await page.getByRole("button", { name: "查看问题历史", exact: true }).click();
  const history = page.locator("section").filter({
    has: page.getByRole("heading", { name: "研究问题历史", exact: true }),
  });
  await expect(history.locator(".record-card")).toHaveCount(20);
  await history
    .getByRole("button", { name: "加载更多问题历史", exact: true })
    .click();
  await expect(history.locator(".record-card")).toHaveCount(25);
  await expect(history.locator(".record-card").last().locator("p")).toHaveText(
    "后页研究问题",
  );
  await page.goto(`/decisions/${decision.id}`);
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  await dialog
    .getByRole("checkbox", { name: "分页候选假设23", exact: true })
    .check();
  await dialog
    .getByRole("button", { name: "加载更多可选假设", exact: true })
    .click();
  await expect(
    dialog.getByRole("checkbox", { name: "分页候选假设23", exact: true }),
  ).toBeChecked();
  await dialog
    .getByRole("checkbox", { name: "分页候选假设0", exact: true })
    .check();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const saved = (
    await (await page.request.get(`/api/v1/decisions/${decision.id}`)).json()
  ).data;
  expect(saved.current_revision).toBe(26);
  expect(
    saved.revision.hypotheses
      .map((row: { hypothesis_id: string }) => row.hypothesis_id)
      .sort(),
  ).toEqual([hypothesisIds[0], hypothesisIds[23]].sort());
  await page
    .getByRole("button", { name: "加载更多决策历史版本", exact: true })
    .click();
  await page.getByLabel("决策版本", { exact: true }).selectOption("1");
  await expect(
    page.getByRole("heading", { name: "原始决策", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("原始理由", { exact: true })).toBeVisible();
  await expect(page.getByLabel("切换当前课题")).toHaveValue(project.id);
});
