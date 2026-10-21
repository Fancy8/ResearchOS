import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test.setTimeout(60000);
const root = path.resolve(process.cwd(), "..");
const python = path.join(root, "runtime/venv/Scripts/python.exe");
async function account(page: Page) {
  const email = `creation-${crypto.randomUUID()}@example.com`;
  const token = execFileSync(
    python,
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  const origin = { Origin: "http://localhost:3000" };
  expect(
    (
      await page.request.post("/api/v1/auth/register", {
        headers: origin,
        data: {
          email,
          password: "ResearchOS-creation-2026",
          display_name: "创建恢复验收",
          invitation_token: token,
        },
      })
    ).status(),
  ).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-creation-2026" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    ...origin,
    "X-CSRF-Token": (await login.json()).data.csrf_token,
  };
  expect(
    (
      await page.request.put("/api/v1/onboarding", {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
        data: {
          project_title: "原创建课题",
          question: "Original creation question",
          research_stage: "experimentation",
        },
      })
    ).status(),
  ).toBe(200);
  async function read(endpoint: string) {
    const response = await page.request.get(`/api/v1${endpoint}`);
    expect(response.status()).toBe(200);
    return (await response.json()).data;
  }
  const project = await read("/projects/current");
  const me = await read("/me");
  const key = (kind: string) => `researchos.${me.workspace_id}.create.${kind}`;
  const journal = (kind: string) =>
    page.evaluate((key) => {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    }, key(kind));
  return { headers, project, me, read, key, journal };
}

async function openNote(page: Page, title: string) {
  await page.goto("/notes");
  await page.getByRole("button", { name: "新建笔记", exact: true }).click();
  const form = page.getByRole("dialog");
  await form.getByLabel("笔记标题", { exact: true }).fill(title);
  return form;
}

for (const kind of ["project", "thread", "note"] as const) {
  test(`lost ${kind} creation response replays one object instead of creating a second`, async ({
    page,
  }) => {
    const { project, read } = await account(page);
    const endpoint =
      kind === "thread"
        ? `/projects/${project.id}/threads`
        : kind === "project"
          ? "/projects"
          : "/notes";
    const pagePath =
      kind === "thread"
        ? `/projects/${project.id}`
        : kind === "project"
          ? "/projects"
          : "/notes";
    const trigger =
      kind === "project"
        ? "新建课题"
        : kind === "thread"
          ? "新增线索"
          : "新建笔记";
    const label =
      kind === "project"
        ? "课题名称"
        : kind === "thread"
          ? "研究线索标题"
          : "笔记标题";
    const attempts: { key?: string; body: object; id: string; path: string }[] =
      [];
    await page.route(`**/api/v1${endpoint}`, async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      attempts.push({
        key: route.request().headers()["idempotency-key"],
        body: route.request().postDataJSON(),
        id: (await response.json()).data.id,
        path: new URL(route.request().url()).pathname,
      });
      if (attempts.length === 1) await route.abort("failed");
      else await route.fulfill({ response });
    });
    await page.goto(pagePath);
    await page.getByRole("button", { name: trigger, exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(label, { exact: true }).fill("原始创建输入");
    if (kind === "thread")
      await dialog
        .getByLabel("你希望解决什么研究问题？", { exact: true })
        .fill("Original target question");
    await dialog.getByRole("button", { name: "保存", exact: true }).click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await dialog
      .getByRole("button", { name: /^(保存|重试原创建请求)$/ })
      .click();
    await expect.poll(() => attempts.length).toBe(2);
    expect(attempts[1]).toEqual(attempts[0]);
    expect(
      (await read(endpoint)).filter(
        (row: { title: string }) => row.title === "原始创建输入",
      ),
    ).toHaveLength(1);
  });
}

test("unknown note creation survives close, reopen and reload without changing its input or key", async ({
  page,
}) => {
  const { journal, read } = await account(page);
  const requests: { key?: string; id: string; body: object }[] = [];
  await page.route("**/api/v1/notes", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    requests.push({
      key: route.request().headers()["idempotency-key"],
      id: (await response.json()).data.id,
      body: route.request().postDataJSON(),
    });
    if (requests.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  let form = await openNote(page, "跨刷新保留的笔记");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  const original = await journal("note");
  await form.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "新建笔记", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "新建笔记", exact: true }).click();
  form = page.getByRole("dialog");
  await expect(form.getByLabel("笔记标题", { exact: true })).toHaveValue(
    "跨刷新保留的笔记",
  );
  await expect(form.getByLabel("笔记标题", { exact: true })).toBeDisabled();
  await form
    .getByRole("button", { name: "重试原创建请求", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/notes/${requests[0].id}$`));
  expect(requests[1]).toEqual(requests[0]);
  expect((await journal("note")).key).toBe(original.key);
  expect(await read("/notes")).toHaveLength(1);
});

test("thread recovery retains its original parent after navigation and header changes", async ({
  page,
}) => {
  const { headers, project, journal, read } = await account(page);
  const otherResponse = await page.request.post("/api/v1/projects", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { title: "另一个创建课题" },
  });
  expect(otherResponse.status()).toBe(201);
  const other = (await otherResponse.json()).data;
  const requests: { path: string; key?: string; id: string; body: object }[] =
    [];
  await page.route(
    `**/api/v1/projects/${project.id}/threads`,
    async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      requests.push({
        path: new URL(route.request().url()).pathname,
        key: route.request().headers()["idempotency-key"],
        id: (await response.json()).data.id,
        body: route.request().postDataJSON(),
      });
      if (requests.length === 1) await route.abort("failed");
      else await route.fulfill({ response });
    },
  );
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("button", { name: "新增线索", exact: true }).click();
  let form = page.getByRole("dialog");
  await form
    .getByLabel("研究线索标题", { exact: true })
    .fill("固定原课题的线索");
  await form
    .getByLabel("你希望解决什么研究问题？", { exact: true })
    .fill("Original parent question");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  const original = await journal("thread");
  await page.goto(`/projects/${other.id}`);
  await page
    .getByRole("combobox", { name: "切换当前课题", exact: true })
    .selectOption(other.id);
  await page.getByRole("button", { name: "新增线索", exact: true }).click();
  form = page.getByRole("dialog");
  await expect(
    form.getByText(`原创建目标：${project.title}`, { exact: true }),
  ).toBeVisible();
  await form
    .getByRole("button", { name: "重试原创建请求", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/threads/${requests[0].id}$`));
  expect(requests[1]).toEqual(requests[0]);
  expect((await journal("thread")).parentId).toBe(original.parentId);
  expect(
    (await read(`/projects/${project.id}/threads`)).filter(
      (row: { title: string }) => row.title === "固定原课题的线索",
    ),
  ).toHaveLength(1);
  expect(await read(`/projects/${other.id}/threads`)).toHaveLength(0);
});

test("replaying a project creation does not replace a newer cached project with its old receipt", async ({
  page,
}) => {
  const { headers, read } = await account(page);
  let id = "";
  let posts = 0;
  await page.route("**/api/v1/projects", async (route) => {
    const response = await route.fetch();
    id = (await response.json()).data.id;
    posts++;
    if (posts === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await page.goto("/projects");
  await page.getByRole("button", { name: "新建课题", exact: true }).click();
  let form = page.getByRole("dialog");
  await form.getByLabel("课题名称", { exact: true }).fill("创建时的课题标题");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  const edited = await page.request.patch(`/api/v1/projects/${id}`, {
    headers,
    data: { expected_version: 1, title: "后来已确认的课题标题" },
  });
  expect(edited.status()).toBe(200);
  await page.goto(`/projects/${id}`);
  await expect(
    page.getByRole("heading", { name: "后来已确认的课题标题", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: /^研究课题/ })
    .first()
    .click();
  await page.getByRole("button", { name: "新建课题", exact: true }).click();
  form = page.getByRole("dialog");
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/projects/${id}`, async (route) => {
    const response = await route.fetch();
    await barrier;
    await route.fulfill({ response });
  });
  try {
    await form
      .getByRole("button", { name: "重试原创建请求", exact: true })
      .click();
    await expect.poll(() => posts).toBe(2);
    await expect(page).toHaveURL(new RegExp(`/projects/${id}$`));
    await expect(
      page.getByRole("heading", { name: "后来已确认的课题标题", exact: true }),
    ).toBeVisible();
    expect(posts).toBe(2);
    expect((await read(`/projects/${id}`)).version).toBe(2);
  } finally {
    release();
  }
});

test("a known validation rejection permits correction using the same unconsumed key", async ({
  page,
}) => {
  const { journal, read } = await account(page);
  const requests: { key?: string; status: number }[] = [];
  await page.route("**/api/v1/projects", async (route) => {
    const response = await route.fetch();
    requests.push({
      key: route.request().headers()["idempotency-key"],
      status: response.status(),
    });
    await route.fulfill({ response });
  });
  await page.goto("/projects");
  await page.getByRole("button", { name: "新建课题", exact: true }).click();
  const form = page.getByRole("dialog");
  await form.getByLabel("课题名称", { exact: true }).fill(" ");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  expect((await journal("project")).phase).toBe("editable");
  await expect(form.getByLabel("课题名称", { exact: true })).toBeEnabled();
  await form.getByLabel("课题名称", { exact: true }).fill("修正后的创建标题");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "创建确认回执", exact: true }),
  ).toBeVisible();
  expect(requests.map((value) => value.status)).toEqual([422, 201]);
  expect(requests[1].key).toBe(requests[0].key);
  expect(
    (await read("/projects")).filter(
      (row: { title: string }) => row.title === "修正后的创建标题",
    ),
  ).toHaveLength(1);
});

test("precommit service failure freezes the original note until the user retries it", async ({
  page,
}) => {
  const { journal, read } = await account(page);
  const keys: (string | undefined)[] = [];
  await page.route("**/api/v1/notes", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1)
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "TEST_SERVICE_DOWN",
            message: "验收：创建前服务暂不可用",
          },
        }),
      });
    else await route.fulfill({ response: await route.fetch() });
  });
  const form = await openNote(page, "提交前失败的笔记");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByRole("alert")).toContainText("创建前服务暂不可用");
  expect(await read("/notes")).toHaveLength(0);
  const original = await journal("note");
  await expect(form.getByLabel("笔记标题", { exact: true })).toBeDisabled();
  await form
    .getByRole("button", { name: "重试原创建请求", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "创建确认回执", exact: true }),
  ).toBeVisible();
  expect(keys).toEqual([original.key, original.key]);
  expect(await read("/notes")).toHaveLength(1);
});

test("confirmed creation remains visible when all following project reads fail", async ({
  page,
}) => {
  const { read } = await account(page);
  let posts = 0;
  let id = "";
  await page.goto("/projects");
  await page.getByRole("button", { name: "新建课题", exact: true }).click();
  const form = page.getByRole("dialog");
  await form.getByLabel("课题名称", { exact: true }).fill("读取失败仍已创建");
  await page.route("**/api/v1/projects**", async (route) => {
    if (route.request().method() === "POST") {
      posts++;
      const response = await route.fetch();
      id = (await response.json()).data.id;
      await route.fulfill({ response });
    } else
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "TEST_READ_DOWN",
            message: "验收：创建后的读取暂不可用",
          },
        }),
      });
  });
  await form.getByRole("button", { name: "保存", exact: true }).click();
  const receipt = page.getByRole("region", {
    name: "创建确认回执",
    exact: true,
  });
  await expect(receipt).toContainText("创建已确认");
  await expect(
    page.getByRole("alert").filter({ hasText: "创建后的读取暂不可用" }).first(),
  ).toBeVisible();
  expect(posts).toBe(1);
  expect((await read(`/projects/${id}`)).title).toBe("读取失败仍已创建");
  await page.unroute("**/api/v1/projects**");
  await receipt
    .getByRole("button", { name: "重读已有记录", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "读取失败仍已创建", exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("storage failure stops creation before the request while preserving unsent input", async ({
  page,
}) => {
  const { key, journal, read } = await account(page);
  const form = await openNote(page, "存储失败仍保留输入");
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/notes"
    )
      posts++;
  });
  await page.evaluate((key) => {
    const saved = Storage.prototype.setItem;
    (
      window as unknown as { restoreCreationStorage: () => void }
    ).restoreCreationStorage = () => {
      Storage.prototype.setItem = saved;
    };
    Storage.prototype.setItem = function (k, value) {
      if (k === key)
        throw new DOMException("fixture quota", "QuotaExceededError");
      return saved.call(this, k, value);
    };
  }, key("note"));
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByRole("alert")).toContainText(
    "无法保存本机创建恢复记录",
  );
  expect(posts).toBe(0);
  expect(await journal("note")).toBeNull();
  expect(await read("/notes")).toHaveLength(0);
  await page.evaluate(() =>
    (
      window as unknown as { restoreCreationStorage: () => void }
    ).restoreCreationStorage(),
  );
  await form
    .getByRole("button", { name: "重新读取恢复记录", exact: true })
    .click();
  await expect(form.getByLabel("笔记标题", { exact: true })).toHaveValue(
    "存储失败仍保留输入",
  );
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "创建确认回执", exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("known creation survives receipt storage failure and is repaired by a read", async ({
  page,
}) => {
  const { key, journal, read } = await account(page);
  const form = await openNote(page, "本机回执失败仍已创建");
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/notes"
    )
      posts++;
  });
  await page.evaluate((key) => {
    const saved = Storage.prototype.setItem;
    (
      window as unknown as { restoreCreationStorage: () => void }
    ).restoreCreationStorage = () => {
      Storage.prototype.setItem = saved;
    };
    Storage.prototype.setItem = function (k, value) {
      if (k === key && JSON.parse(value).phase === "accepted")
        throw new DOMException("fixture quota", "QuotaExceededError");
      return saved.call(this, k, value);
    };
  }, key("note"));
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    form.getByText("创建已确认。详情读取失败时不需要重新创建。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(form.getByRole("alert")).toContainText(
    "无法保存本机创建恢复记录",
  );
  expect((await journal("note")).phase).toBe("unknown");
  await form
    .getByRole("button", { name: "读取已创建记录", exact: true })
    .click();
  await expect(
    form.getByText("最近一次读取：本机回执失败仍已创建 · v1", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
  await page.evaluate(() =>
    (
      window as unknown as { restoreCreationStorage: () => void }
    ).restoreCreationStorage(),
  );
  await form
    .getByRole("button", { name: "读取已创建记录", exact: true })
    .click();
  await expect.poll(async () => (await journal("note")).phase).toBe("accepted");
  const accepted = await journal("note");
  expect(Object.keys(accepted).sort()).toEqual(
    [
      "version",
      "workspaceId",
      "kind",
      "key",
      "createdAt",
      "parentId",
      "contextTitle",
      "body",
      "phase",
      "resourceId",
    ].sort(),
  );
  await form.getByRole("link", { name: "打开已创建记录", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/notes/${accepted.resourceId}$`));
  expect(posts).toBe(1);
  expect(await read("/notes")).toHaveLength(1);
});
