import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function account(page: Page) {
  const root = path.resolve(process.cwd(), "..");
  const email = `decision-${crypto.randomUUID()}@example.com`;
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
      password: "ResearchOS-decision-state-2026",
      display_name: "决策验收",
      invitation_token: invitation,
    },
  });
  expect(registration.status()).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-decision-state-2026" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    ...origin,
    "X-CSRF-Token": (await login.json()).data.csrf_token,
  };
  const onboarding = await page.request.put("/api/v1/onboarding", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      project_title: "决策验收课题",
      question: "失败后能否保留原判断？",
      research_stage: "experimentation",
    },
  });
  expect(onboarding.status()).toBe(200);
  async function read(endpoint: string) {
    const result = await page.request.get(`/api/v1${endpoint}`);
    expect(result.status()).toBe(200);
    return (await result.json()).data;
  }
  const project = await read("/projects/current");
  const thread = (await read(`/projects/${project.id}/threads`))[0];
  async function create(endpoint: string, data: object) {
    const result = await page.request.post(`/api/v1${endpoint}`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data,
    });
    expect(result.status()).toBe(201);
    return (await result.json()).data;
  }
  return { headers, project, thread, read, create };
}
type Attempt = { key: string | undefined; body: Record<string, unknown> };
function record(route: Route): Attempt {
  return {
    key: route.request().headers()["idempotency-key"],
    body: route.request().postDataJSON(),
  };
}
async function unavailable(route: Route, message: string) {
  await route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "TEST_UNAVAILABLE", message } }),
  });
}
function content(text: string) {
  return {
    type: "doc",
    content: [{ type: "paragraph", content: [{ type: "text", text }] }],
  };
}

test("lost decision creation response replays its original key and committed snapshots after basis changes", async ({
  page,
}) => {
  test.setTimeout(90000);
  const { headers, thread, create, read } = await account(page);
  const note = await create("/notes", {
    title: "后页原始依据笔记",
    content: content("原始笔记内容"),
  });
  for (let i = 0; i < 21; i++)
    await create("/notes", { title: `后来的笔记 ${i}` });
  const hypothesis = await create(`/threads/${thread.id}/hypotheses`, {
    statement: "原始假设依据",
  });
  const attempts: Attempt[] = [];
  await page.route(
    `**/api/v1/threads/${thread.id}/decisions`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      attempts.push(record(route));
      if (attempts.length === 1) {
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        await route.abort("failed");
      } else await route.continue();
    },
  );
  await page.goto(`/threads/${thread.id}`);
  await page.getByRole("button", { name: "+ 记录判断", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "记录研究决策",
    exact: true,
  });
  await dialog.getByLabel("决策标题").fill("不重复创建的研究判断");
  await dialog.getByLabel("为什么采取这个决定？").fill("保留首次提交的理由");
  await dialog
    .getByRole("checkbox", { name: hypothesis.statement, exact: true })
    .check();
  await dialog
    .getByRole("button", { name: "加载更多决策可选笔记", exact: true })
    .click();
  await dialog.getByRole("checkbox", { name: note.title, exact: true }).check();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("checkbox", { name: note.title, exact: true }),
  ).toBeChecked();
  await expect(dialog.getByLabel("决策标题")).toBeDisabled();
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  const changed = await page.request.put(`/api/v1/notes/${note.id}`, {
    headers,
    data: {
      expected_version: 1,
      title: "另一个版本的笔记",
      content: content("后来内容"),
    },
  });
  expect(changed.status()).toBe(200);
  const removed = await page.request.delete(`/api/v1/notes/${note.id}`, {
    headers,
    data: { expected_version: 2 },
  });
  expect(removed.status()).toBe(200);
  const altered = await page.request.patch(
    `/api/v1/hypotheses/${hypothesis.id}`,
    {
      headers,
      data: {
        expected_version: 1,
        statement: "后来的假设",
        status: "contradicted",
      },
    },
  );
  expect(altered.status()).toBe(200);
  await page.getByRole("button", { name: "+ 记录判断", exact: true }).click();
  await expect(
    dialog.getByRole("checkbox", { name: note.title, exact: true }),
  ).toBeChecked();
  await dialog.getByRole("button", { name: "重试原请求", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1]).toEqual(attempts[0]);
  const decisions = await read(`/threads/${thread.id}/decisions`);
  expect(decisions).toHaveLength(1);
  const saved = await read(`/decisions/${decisions[0].id}/revisions/1`);
  expect(saved.notes[0].note_version).toBe(1);
  expect(saved.notes[0].content_snapshot).toEqual(note.content);
  expect(saved.hypotheses[0].statement_snapshot).toBe(hypothesis.statement);
  const events = await read("/activity?limit=100");
  expect(
    events.filter(
      (event: { target_id: string; event_type: string }) =>
        event.target_id === decisions[0].id &&
        event.event_type === "decision_created",
    ),
  ).toHaveLength(1);
});

test("lost decision revision response can confirm an earlier committed revision after another writer advances", async ({
  page,
}) => {
  const { project, thread, create, read } = await account(page);
  const decision = await create(`/threads/${thread.id}/decisions`, {
    title: "修订回执决策",
    reason: "原始理由",
    decision_type: "adopt",
  });
  const task = await create("/tasks", {
    project_id: project.id,
    thread_id: thread.id,
    decision_id: decision.id,
    title: "保留第一版来源",
  });
  const attempts: Attempt[] = [];
  await page.route(
    `**/api/v1/decisions/${decision.id}/revisions`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      attempts.push(record(route));
      if (attempts.length === 1) {
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        await route.abort("failed");
      } else await route.continue();
    },
  );
  await page.goto(`/decisions/${decision.id}`);
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "修订研究决策（保留原版本）",
    exact: true,
  });
  await dialog.getByLabel("新的决策理由").fill("第二版已提交但响应丢失");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await create(`/decisions/${decision.id}/revisions`, {
    expected_revision: 2,
    title: "第三版外部修订",
    reason: "另一页的理由",
    decision_type: "defer",
  });
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  await expect(dialog.getByLabel("新的决策理由")).toHaveValue(
    "第二版已提交但响应丢失",
  );
  await dialog.getByRole("button", { name: "重试原请求", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
  expect(attempts[0].body.expected_revision).toBe(1);
  await expect(
    page.getByRole("status").filter({ hasText: "研究决策 v2 已保存" }),
  ).toBeVisible();
  expect((await read(`/decisions/${decision.id}`)).current_revision).toBe(3);
  expect(await read(`/decisions/${decision.id}/revisions`)).toHaveLength(3);
  expect((await read(`/decisions/${decision.id}/revisions/2`)).reason).toBe(
    "第二版已提交但响应丢失",
  );
  expect((await read(`/tasks/${task.id}`)).source_revision_no).toBe(1);
});

test("decision save blocks duplicate submits and reuses its intent after a precommit failure", async ({
  page,
}) => {
  const { thread, read } = await account(page);
  const attempts: Attempt[] = [];
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    `**/api/v1/threads/${thread.id}/decisions`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      attempts.push(record(route));
      if (attempts.length === 1) {
        await held;
        await unavailable(route, "决策暂时无法保存");
      } else await route.continue();
    },
  );
  await page.goto(`/threads/${thread.id}`);
  await page.getByRole("button", { name: "+ 记录判断", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "记录研究决策",
    exact: true,
  });
  await dialog.getByLabel("决策标题").fill("一次保存意图");
  await dialog
    .getByLabel("为什么采取这个决定？")
    .fill("暂时失败后仍是同一请求");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(() => attempts.length).toBe(1);
  await dialog.locator("form").evaluate((form) => {
    if (!(form instanceof HTMLFormElement))
      throw new Error("Expected decision form");
    form.requestSubmit();
    form.requestSubmit();
  });
  await expect(
    dialog.getByRole("button", { name: "保存中…", exact: true }),
  ).toBeDisabled();
  expect(attempts).toHaveLength(1);
  release();
  await expect(dialog.getByRole("alert")).toContainText("决策暂时无法保存");
  expect(await read(`/threads/${thread.id}/decisions`)).toHaveLength(0);
  await dialog.getByRole("button", { name: "重试原请求", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts[1]).toEqual(attempts[0]);
  expect(await read(`/threads/${thread.id}/decisions`)).toHaveLength(1);
});

test("known decision validation and missing-basis rejections preserve editable input and the original key", async ({
  page,
}) => {
  const { headers, thread, create, read } = await account(page);
  const note = await create("/notes", { title: "保存前被移入回收站" });
  const attempts: Attempt[] = [];
  await page.route(
    `**/api/v1/threads/${thread.id}/decisions`,
    async (route) => {
      if (route.request().method() === "POST") attempts.push(record(route));
      await route.continue();
    },
  );
  await page.goto(`/threads/${thread.id}`);
  await page.getByRole("button", { name: "+ 记录判断", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "记录研究决策",
    exact: true,
  });
  await dialog.getByLabel("决策标题").fill("修正仍用原请求键");
  await dialog.getByLabel("为什么采取这个决定？").fill("   ");
  await dialog.getByRole("checkbox", { name: note.title, exact: true }).check();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog.getByLabel("为什么采取这个决定？")).toBeEnabled();
  await expect(dialog.getByLabel("为什么采取这个决定？")).toHaveValue("   ");
  expect(await read(`/threads/${thread.id}/decisions`)).toHaveLength(0);
  expect(
    (
      await page.request.delete(`/api/v1/notes/${note.id}`, {
        headers,
        data: { expected_version: 1 },
      })
    ).status(),
  ).toBe(200);
  await dialog.getByLabel("为什么采取这个决定？").fill("修正后的理由");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(() => attempts.length).toBe(2);
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("checkbox", { name: note.title, exact: true }),
  ).toBeEnabled();
  await dialog
    .getByRole("checkbox", { name: note.title, exact: true })
    .uncheck();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts).toHaveLength(3);
  expect(new Set(attempts.map((attempt) => attempt.key)).size).toBe(1);
  expect(attempts[1].body.note_ids).toEqual([note.id]);
  expect(attempts[2].body.note_ids).toEqual([]);
  expect(await read(`/threads/${thread.id}/decisions`)).toHaveLength(1);
});

test("decision conflict read failure and a second concurrent update require explicit comparison each time", async ({
  page,
}) => {
  const { thread, create, read } = await account(page);
  const decision = await create(`/threads/${thread.id}/decisions`, {
    title: "多次竞争决策",
    reason: "初版",
    decision_type: "adopt",
  });
  let failRead = false;
  const attempts: Attempt[] = [];
  await page.route(`**/api/v1/decisions/${decision.id}`, async (route) => {
    if (failRead) await unavailable(route, "服务器版本暂不可读");
    else await route.continue();
  });
  await page.route(
    `**/api/v1/decisions/${decision.id}/revisions`,
    async (route) => {
      if (route.request().method() === "POST") attempts.push(record(route));
      await route.continue();
    },
  );
  await page.goto(`/decisions/${decision.id}`);
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "修订研究决策（保留原版本）",
    exact: true,
  });
  await dialog.getByLabel("新的决策理由").fill("本页一直保留的理由");
  await dialog.getByLabel("本次完整方案").fill("手动保留的方案");
  await create(`/decisions/${decision.id}/revisions`, {
    expected_revision: 1,
    title: "竞争版本二",
    reason: "服务器二版理由",
    content: "服务器完整方案二",
    decision_type: "adjust",
  });
  failRead = true;
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  const comparison = dialog.getByRole("region", {
    name: "服务器决策版本",
    exact: true,
  });
  await expect(comparison.getByRole("alert")).toContainText(
    "服务器版本暂不可读",
  );
  await expect(
    dialog.getByRole("button", { name: "保存", exact: true }),
  ).toBeDisabled();
  await expect(dialog.getByLabel("新的决策理由")).toHaveValue(
    "本页一直保留的理由",
  );
  failRead = false;
  await comparison
    .getByRole("button", { name: "重新读取服务器版本", exact: true })
    .click();
  await expect(
    comparison.getByRole("heading", {
      name: "服务器已保存决策 v2",
      exact: true,
    }),
  ).toBeVisible();
  await expect(comparison).toContainText("服务器完整方案二");
  await comparison
    .getByRole("button", {
      name: "采用服务器最新版本作为修订基准",
      exact: true,
    })
    .click();
  await create(`/decisions/${decision.id}/revisions`, {
    expected_revision: 2,
    title: "竞争版本三",
    reason: "服务器三版理由",
    decision_type: "defer",
  });
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    comparison.getByRole("heading", {
      name: "服务器已保存决策 v3",
      exact: true,
    }),
  ).toBeVisible();
  await comparison.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "../artifacts/decision-conflict-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await comparison.scrollIntoViewIfNeeded();
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth <= element.clientWidth + 1,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../artifacts/decision-conflict-mobile.png",
    fullPage: true,
  });
  await expect(dialog.getByLabel("本次完整方案")).toHaveValue("手动保留的方案");
  await comparison
    .getByRole("button", {
      name: "采用服务器最新版本作为修订基准",
      exact: true,
    })
    .click();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(attempts.map((attempt) => attempt.body.expected_revision)).toEqual([
    1, 2, 3,
  ]);
  expect(new Set(attempts.map((attempt) => attempt.key)).size).toBe(3);
  const latest = await read(`/decisions/${decision.id}`);
  expect(latest.current_revision).toBe(4);
  expect(latest.revision.reason).toBe("本页一直保留的理由");
  expect((await read(`/decisions/${decision.id}/revisions/1`)).reason).toBe(
    "初版",
  );
});

test("side panel refresh failure after confirmed decision save only retries a read", async ({
  page,
}) => {
  const { thread, create, read } = await account(page);
  const decision = await create(`/threads/${thread.id}/decisions`, {
    title: "侧栏刷新决策",
    reason: "原理由",
    decision_type: "adopt",
  });
  let failRead = false,
    posts = 0;
  await page.route(`**/api/v1/decisions/${decision.id}`, async (route) => {
    if (failRead) await unavailable(route, "侧栏读取暂时失败");
    else await route.continue();
  });
  await page.route(
    `**/api/v1/decisions/${decision.id}/revisions`,
    async (route) => {
      if (route.request().method() === "POST") {
        posts++;
        failRead = true;
      }
      await route.continue();
    },
  );
  await page.goto(`/threads/${thread.id}`);
  await page
    .getByRole("button", { name: "查看决策与依据", exact: true })
    .click();
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "修订研究决策（保留原版本）",
    exact: true,
  });
  await dialog.getByLabel("新的决策理由").fill("保存确实成功的理由");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(
    page.getByText(
      "保存已确认，详情暂未重新加载。重试只读取内容，不再提交决策。",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "研究决策 v2 已保存" }),
  ).toBeVisible();
  expect((await read(`/decisions/${decision.id}`)).current_revision).toBe(2);
  failRead = false;
  await page.getByRole("button", { name: "重试读取决策", exact: true }).click();
  await expect(page.locator(".decision-reason")).toContainText(
    "保存确实成功的理由",
  );
  expect(posts).toBe(1);
  expect(await read(`/decisions/${decision.id}/revisions`)).toHaveLength(2);
});

test("decision detail retains confirmed save feedback and cached content when its background read fails", async ({
  page,
}) => {
  const { thread, create, read } = await account(page);
  const decision = await create(`/threads/${thread.id}/decisions`, {
    title: "详情读取决策",
    reason: "原始缓存内容",
    decision_type: "adopt",
  });
  let failRead = false,
    posts = 0;
  await page.route(`**/api/v1/decisions/${decision.id}`, async (route) => {
    if (failRead) await unavailable(route, "详情刷新暂不可用");
    else await route.continue();
  });
  await page.route(
    `**/api/v1/decisions/${decision.id}/revisions`,
    async (route) => {
      if (route.request().method() === "POST") {
        posts++;
        failRead = true;
      }
      await route.continue();
    },
  );
  await page.goto(`/decisions/${decision.id}`);
  await page
    .getByRole("button", { name: "记录新的决策版本", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "修订研究决策（保留原版本）",
    exact: true,
  });
  await dialog.getByLabel("新的决策理由").fill("服务器已保存的新内容");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const main = page.getByRole("main");
  await expect(
    main.getByRole("status").filter({ hasText: "研究决策 v2 已保存" }),
  ).toBeVisible();
  await expect(main.getByRole("alert")).toContainText("详情刷新暂不可用", {
    timeout: 15000,
  });
  await expect(main.locator(".decision-reason")).toContainText("原始缓存内容");
  failRead = false;
  await main.getByRole("button", { name: "重试", exact: true }).click();
  await expect(main.locator(".decision-reason")).toContainText(
    "服务器已保存的新内容",
  );
  expect(posts).toBe(1);
  expect((await read(`/decisions/${decision.id}`)).current_revision).toBe(2);
});

test("decision response timeout stays unconfirmed and refuses replay beyond the safe receipt window", async ({
  page,
}) => {
  const { thread, read } = await account(page);
  let posts = 0,
    committed = false;
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    `**/api/v1/threads/${thread.id}/decisions`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      posts++;
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      committed = true;
      await held;
      if (!route.request().failure()) await route.fulfill({ response });
    },
  );
  await page.goto(`/threads/${thread.id}`);
  await page.clock.install({ time: new Date() });
  await page.getByRole("button", { name: "+ 记录判断", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "记录研究决策",
    exact: true,
  });
  await dialog.getByLabel("决策标题").fill("超时仍待核对");
  await dialog.getByLabel("为什么采取这个决定？").fill("服务器可能已经完成");
  try {
    await dialog.getByRole("button", { name: "保存", exact: true }).click();
    await expect.poll(() => committed).toBe(true);
    await page.clock.fastForward(31_000);
    await expect(dialog.getByRole("alert")).toContainText(
      "请求超时，结果尚未确认",
    );
    await expect(dialog.getByLabel("决策标题")).toBeDisabled();
    expect(await read(`/threads/${thread.id}/decisions`)).toHaveLength(1);
    await page.clock.setFixedTime(new Date(Date.now() + 24 * 60 * 60 * 1000));
    await dialog
      .getByRole("button", { name: "重试原请求", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toContainText(
      "原请求已超过可安全重试时限",
    );
    expect(posts).toBe(1);
  } finally {
    release();
  }
});
