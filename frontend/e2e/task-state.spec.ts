import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function account(page: Page) {
  const root = path.resolve(process.cwd(), "..");
  const email = `tasks-${crypto.randomUUID()}@example.com`;
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
      password: "ResearchOS-task-state-2026",
      display_name: "任务验收",
      invitation_token: invitation,
    },
  });
  expect(registration.status()).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-task-state-2026" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    ...origin,
    "X-CSRF-Token": (await login.json()).data.csrf_token,
  };
  const onboarding = await page.request.put("/api/v1/onboarding", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      project_title: "任务验收课题",
      question: "失败能否安全恢复？",
      research_stage: "experimentation",
    },
  });
  expect(onboarding.status()).toBe(200);
  const project = (
    await (await page.request.get("/api/v1/projects/current")).json()
  ).data;
  async function create(endpoint: string, data: object) {
    const result = await page.request.post(`/api/v1${endpoint}`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data,
    });
    expect(result.status()).toBe(201);
    return (await result.json()).data;
  }
  async function read(id: string) {
    return (await (await page.request.get(`/api/v1/tasks/${id}`)).json()).data;
  }
  return { headers, project, create, read };
}

async function unavailable(route: Route, message: string) {
  await route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "TEST_UNAVAILABLE", message } }),
  });
}

test("task filters paginate on server, survive refresh and retain loaded rows on page failure", async ({
  page,
}) => {
  test.setTimeout(90000);
  const { project, create } = await account(page);
  for (let i = 0; i < 23; i++)
    await create("/tasks", {
      project_id: project.id,
      title: `筛选命中 ${i}${i === 0 ? "X".repeat(230) : ""}`,
      priority: "high",
      due_date: "2026-10-15",
    });
  for (let i = 0; i < 5; i++)
    await create("/tasks", {
      project_id: project.id,
      title: `无日期任务 ${i}`,
    });
  const second = await create("/projects", { title: "另一个课题" });
  await create("/tasks", {
    project_id: second.id,
    title: "另课题命中",
    priority: "high",
    due_date: "2026-10-15",
  });
  await page.goto("/tasks");
  await expect(page.getByRole("article")).toHaveCount(20);
  await page.getByLabel("筛选任务状态").selectOption("todo");
  await page.getByLabel("筛选优先级").selectOption("high");
  await page.getByLabel("截止日期从").fill("2026-10-15");
  await page.getByLabel("截止日期至").fill("2026-10-15");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(page).toHaveURL(/status=todo.*priority=high/);
  await expect(page.getByRole("article")).toHaveCount(20);
  await expect(
    page.getByRole("article").filter({ hasText: "无日期任务" }),
  ).toHaveCount(0);
  let fail = true;
  await page.route("**/api/v1/tasks?**", async (route) => {
    if (fail && new URL(route.request().url()).searchParams.has("cursor"))
      await unavailable(route, "任务后页暂时不可用");
    else await route.continue();
  });
  await page.getByRole("button", { name: "加载更多任务", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "任务后页暂时不可用",
    {
      timeout: 15000,
    },
  );
  await expect(page.getByRole("article")).toHaveCount(20);
  await expect(
    page.getByRole("heading", { name: "没有符合筛选条件的任务" }),
  ).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("article")).toHaveCount(23);
  await page.reload();
  await expect(page.getByLabel("筛选优先级")).toHaveValue("high");
  await expect(page.getByLabel("截止日期从")).toHaveValue("2026-10-15");
  await expect(page.getByRole("article")).toHaveCount(20);
  await page.getByLabel("课题范围").selectOption("all");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(page).toHaveURL(/scope=all/);
  await expect(
    page.getByRole("article", { name: "另课题命中", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "加载更多任务", exact: true }).click();
  await expect(page.getByRole("article")).toHaveCount(24);
  await page.goBack();
  await expect(page.getByLabel("课题范围")).toHaveValue("current");
  await expect(
    page.getByRole("article", { name: "另课题命中", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("筛选任务状态").selectOption("done");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(
    page.getByRole("heading", { name: "没有符合筛选条件的任务" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../artifacts/task-filters-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../artifacts/task-filters-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("筛选任务状态").selectOption("todo");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(page.getByRole("article").first()).toBeVisible();
  const longTask = page
    .getByRole("article")
    .filter({ hasText: "X".repeat(230) });
  // The matching task is older than page one after a full reload.
  if (
    await page
      .getByRole("button", { name: "加载更多任务", exact: true })
      .isVisible()
  )
    await page
      .getByRole("button", { name: "加载更多任务", exact: true })
      .click();
  await expect(longTask).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../artifacts/task-rows-mobile.png",
    fullPage: true,
  });
});

test("initial task read failure has a retry and invalid filters never masquerade as an empty list", async ({
  page,
}) => {
  const { project, create } = await account(page);
  await create("/tasks", { project_id: project.id, title: "重试后可见" });
  let fail = true;
  const reads: string[] = [];
  await page.route("**/api/v1/tasks?**", async (route) => {
    reads.push(route.request().url());
    if (fail) await unavailable(route, "任务读取失败");
    else await route.continue();
  });
  await page.goto("/tasks");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "任务读取失败",
    {
      timeout: 15000,
    },
  );
  await expect(
    page.getByRole("heading", { name: "清楚知道下一步" }),
  ).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(
    page.getByRole("article", { name: "重试后可见", exact: true }),
  ).toBeVisible();
  await page.goto("/tasks?due_from=2026-10-16&due_to=2026-10-15");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "筛选条件无效",
  );
  expect(
    reads.some(
      (url) => new URL(url).searchParams.get("due_from") === "2026-10-16",
    ),
  ).toBe(false);
  await page.getByRole("button", { name: "重置筛选" }).click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(
    page.getByRole("article", { name: "重试后可见", exact: true }),
  ).toBeVisible();
});

test("task status failure keeps its original request and blocks double submission", async ({
  page,
}) => {
  const { project, create, read } = await account(page);
  const task = await create("/tasks", {
    project_id: project.id,
    title: "失败后完成",
  });
  const attempts: object[] = [];
  let release: () => void = () => {};
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/tasks/${task.id}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    attempts.push(route.request().postDataJSON());
    if (attempts.length === 1) await unavailable(route, "状态保存失败");
    else {
      await barrier;
      await route.continue();
    }
  });
  await page.goto("/tasks");
  const row = page.getByRole("article", { name: task.title, exact: true });
  await row
    .getByRole("button", { name: `完成 ${task.title}`, exact: true })
    .click();
  await expect(row.getByRole("alert")).toContainText("状态保存失败");
  await expect(row.locator(".badge")).toHaveText("待开始");
  expect((await read(task.id)).version).toBe(1);
  await row.getByRole("button", { name: "重试原请求" }).click();
  await expect(
    row.getByRole("button", { name: `完成 ${task.title}`, exact: true }),
  ).toBeDisabled();
  await expect.poll(() => attempts.length).toBe(2);
  expect(attempts[1]).toEqual(attempts[0]);
  release();
  await expect(row.locator(".badge")).toHaveText("已完成");
  expect((await read(task.id)).version).toBe(2);
  await expect(row.getByRole("alert")).toHaveCount(0);
});

test("lost status response retries the same version and requires reading the committed state", async ({
  page,
}) => {
  const { project, create, read } = await account(page);
  const task = await create("/tasks", {
    project_id: project.id,
    title: "响应丢失任务",
  });
  const attempts: object[] = [];
  await page.route(`**/api/v1/tasks/${task.id}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    attempts.push(route.request().postDataJSON());
    if (attempts.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      await route.abort("failed");
    } else await route.continue();
  });
  await page.goto(`/tasks/${task.id}`);
  await page.getByRole("button", { name: "完成任务", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  expect((await read(task.id)).status).toBe("done");
  await page.getByRole("button", { name: "重试原请求" }).click();
  await expect(
    page.getByText("任务版本已变化。请先读取最新状态，再决定是否操作。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(attempts).toEqual([
    { expected_version: 1, status: "done" },
    { expected_version: 1, status: "done" },
  ]);
  await page.getByRole("button", { name: "读取最新状态" }).click();
  await expect(
    page.getByRole("button", { name: "重新设为待办", exact: true }),
  ).toBeEnabled();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  expect((await read(task.id)).version).toBe(2);
  const events = (
    await (await page.request.get("/api/v1/activity?limit=100")).json()
  ).data;
  expect(
    events.filter(
      (event: { target_id: string; event_type: string }) =>
        event.target_id === task.id && event.event_type === "task_completed",
    ),
  ).toHaveLength(1);
});

test("lost task creation response keeps the same idempotency key across dialog reopen", async ({
  page,
}) => {
  await account(page);
  const attempts: { key: string | undefined; body: object }[] = [];
  await page.route("**/api/v1/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    if (attempts.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort("failed");
    } else await route.continue();
  });
  await page.goto("/tasks");
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "创建科研任务" });
  await dialog.getByLabel("任务名称").fill("同一次创建");
  await dialog.getByLabel("任务说明").fill("响应丢失也要保留的说明");
  await dialog.getByLabel("优先级", { exact: true }).selectOption("high");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog.getByLabel("任务名称")).toHaveValue("同一次创建");
  await expect(dialog.getByLabel("任务名称")).toBeDisabled();
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  const row = page.getByRole("article", { name: "同一次创建", exact: true });
  await row
    .getByRole("button", { name: "完成 同一次创建", exact: true })
    .click();
  await expect(row.locator(".badge")).toHaveText("已完成");
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  await expect(dialog.getByLabel("任务说明")).toHaveValue(
    "响应丢失也要保留的说明",
  );
  await dialog.getByRole("button", { name: "重试原请求" }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1]).toEqual(attempts[0]);
  const tasks = (await (await page.request.get("/api/v1/tasks")).json()).data;
  expect(
    tasks.filter((task: { title: string }) => task.title === "同一次创建"),
  ).toHaveLength(1);
  expect(tasks[0].version).toBe(2);
  // Idempotency replays the original version-1 response. It must not downgrade
  // the version-2 entity already confirmed by the status write, even while a
  // fresh detail read has not yet returned.
  let release: () => void = () => {};
  const heldRead = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/tasks/${tasks[0].id}`, async (route) => {
    await heldRead;
    await route.continue();
  });
  try {
    await row.getByRole("link", { name: "同一次创建", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "重新设为待办", exact: true }),
    ).toBeEnabled();
  } finally {
    release();
  }
});

test("task edit conflict retains input until explicit comparison and reopens with latest values", async ({
  page,
}) => {
  const { headers, project, create, read } = await account(page);
  const task = await create("/tasks", {
    project_id: project.id,
    title: "并发编辑任务",
    description: "原说明",
  });
  await page.goto(`/tasks/${task.id}`);
  await page.getByRole("button", { name: "编辑任务", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "编辑科研任务" });
  await dialog.getByLabel("任务说明").fill("本页尚未保存的说明");
  const external = await page.request.patch(`/api/v1/tasks/${task.id}`, {
    headers,
    data: {
      expected_version: 1,
      status: "blocked",
      description: "另一页的说明",
    },
  });
  expect(external.status()).toBe(200);
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    dialog.getByRole("region", { name: "服务器任务版本" }),
  ).toContainText("服务器版本 v2");
  await expect(dialog.getByLabel("任务说明")).toHaveValue("本页尚未保存的说明");
  await expect(
    dialog.getByRole("button", { name: "保存", exact: true }),
  ).toBeDisabled();
  expect((await read(task.id)).description).toBe("另一页的说明");
  await dialog.getByLabel("任务状态").selectOption("blocked");
  await dialog
    .getByLabel("任务说明")
    .fill("人工合并：另一页的说明；本页尚未保存的说明");
  await dialog
    .getByRole("button", { name: "已对照，保留输入继续编辑" })
    .click();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const saved = await read(task.id);
  expect(saved.version).toBe(3);
  expect(saved.status).toBe("blocked");
  expect(saved.description).toBe("人工合并：另一页的说明；本页尚未保存的说明");
  await page.getByRole("button", { name: "编辑任务", exact: true }).click();
  await expect(dialog.getByLabel("任务状态")).toHaveValue("blocked");
  await expect(dialog.getByLabel("任务说明")).toHaveValue(saved.description);
});

test("decision task retry keeps its original revision after the decision advances", async ({
  page,
}) => {
  const { project, create } = await account(page);
  const thread = (
    await (
      await page.request.get(`/api/v1/projects/${project.id}/threads`)
    ).json()
  ).data[0];
  const decision = await create(`/threads/${thread.id}/decisions`, {
    title: "来源冻结决策",
    reason: "首次理由",
    decision_type: "adopt",
  });
  const attempts: { path: string; key: string | undefined; body: object }[] =
    [];
  await page.route(
    `**/api/v1/decisions/${decision.id}/revisions/*/tasks`,
    async (route) => {
      attempts.push({
        path: new URL(route.request().url()).pathname,
        key: route.request().headers()["idempotency-key"],
        body: route.request().postDataJSON(),
      });
      if (attempts.length === 1) {
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        await route.abort("failed");
      } else await route.continue();
    },
  );
  await page.goto(`/threads/${thread.id}`);
  await page.getByRole("button", { name: "创建行动 →", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "从决策创建下一步任务" });
  await dialog.getByLabel("具体行动").fill("冻结来源任务");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await create(`/decisions/${decision.id}/revisions`, {
    expected_revision: 1,
    title: "来源冻结决策",
    reason: "第二版理由",
    decision_type: "adjust",
  });
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page
      .locator(".record-card")
      .filter({ hasText: "来源冻结决策" })
      .locator(".badge"),
  ).toHaveText("v2");
  await page.getByRole("button", { name: "创建行动 →", exact: true }).click();
  await expect(
    dialog.getByText("来自决策 v1：来源冻结决策。保存与重试均保留这个修订。", {
      exact: true,
    }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "重试原请求" }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
  expect(attempts[0].path).toContain("/revisions/1/tasks");
  const tasks = (
    await (
      await page.request.get(`/api/v1/tasks?thread_id=${thread.id}`)
    ).json()
  ).data;
  expect(tasks).toHaveLength(1);
  expect(tasks[0].source_revision_no).toBe(1);
});

test("uncertain task creation cannot replay beyond the idempotency safety window", async ({
  page,
}) => {
  await account(page);
  let attempts = 0;
  await page.route("**/api/v1/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts++;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    await route.abort("failed");
  });
  await page.goto("/tasks");
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "创建科研任务" });
  await dialog.getByLabel("任务名称").fill("超过重试时限");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  // Change only the browser clock, without advancing timers or the database.
  // The guard must reject before issuing another HTTP request.
  await page.clock.setFixedTime(new Date(Date.now() + 24 * 60 * 60 * 1000));
  await dialog.getByRole("button", { name: "重试原请求" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "原请求已超过可安全重试时限",
  );
  expect(attempts).toBe(1);
  await expect(dialog.getByLabel("任务名称")).toHaveValue("超过重试时限");
  const tasks = (await (await page.request.get("/api/v1/tasks")).json()).data;
  expect(tasks).toHaveLength(1);
});
