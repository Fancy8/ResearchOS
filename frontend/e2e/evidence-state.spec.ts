import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { createHash } from "node:crypto";

const ORIGINAL = "Original first page evidence.";
const SECOND = "Original second page evidence.";
const REPLACEMENT = "Replacement first page evidence.";
function failedParseFixture(root: string, fileId: string, markFailed: boolean) {
  const code = `import sys
import psycopg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
values=dotenv_values('.env')
url=make_url(values['RESEARCHOS_ADMIN_DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
with psycopg.connect(url,autocommit=True) as db:
    if sys.argv[2]=='failed':
        result=db.execute("UPDATE paper_files SET parse_status='failed' WHERE id=%s AND upload_status='uploaded'",(sys.argv[1],))
        assert result.rowcount==1
    print(db.execute('SELECT count(*) FROM processing_jobs WHERE paper_file_id=%s',(sys.argv[1],)).fetchone()[0])
`;
  return Number(
    execFileSync(
      path.join(root, "runtime/venv/Scripts/python.exe"),
      ["-c", code, fileId, markFailed ? "failed" : "count"],
      { cwd: root, encoding: "utf-8" },
    ).trim(),
  );
}
async function account(page: Page) {
  const root = path.resolve(process.cwd(), "..");
  const python = path.join(root, "runtime/venv/Scripts/python.exe");
  execFileSync(
    python,
    [
      "-c",
      `from pathlib import Path
from reportlab.pdfgen import canvas
folder=Path('artifacts/fixtures'); folder.mkdir(parents=True,exist_ok=True)
for name,first,second in [('evidence-state-v1.pdf','${ORIGINAL}','${SECOND}'),('evidence-state-v2.pdf','${REPLACEMENT}','Replacement second page evidence.')]:
    doc=canvas.Canvas(str(folder/name))
    doc.drawString(60,720,first); doc.showPage(); doc.drawString(60,720,second); doc.showPage(); doc.save()
`,
    ],
    { cwd: root },
  );
  const email = `evidence-${crypto.randomUUID()}@example.com`;
  const invitation = execFileSync(
    python,
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  const origin = { Origin: "http://localhost:3000" };
  const registration = await page.request.post("/api/v1/auth/register", {
    headers: origin,
    data: {
      email,
      password: "ResearchOS-evidence-state-2026",
      display_name: "证据出处验收",
      invitation_token: invitation,
    },
  });
  expect(registration.status()).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-evidence-state-2026" },
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
          project_title: "证据出处课题",
          question: "Evidence origin question",
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
  const thread = (await read(`/projects/${project.id}/threads`))[0];
  async function create(endpoint: string, data: object) {
    const result = await page.request.post(`/api/v1${endpoint}`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data,
    });
    expect(result.status()).toBe(201);
    return (await result.json()).data;
  }
  const fixture = (version: number) =>
    path.join(root, `artifacts/fixtures/evidence-state-v${version}.pdf`);
  async function upload(version: number, paperId?: string) {
    const buffer = fs.readFileSync(fixture(version));
    const name = path.basename(fixture(version));
    const initialized = await page.request.post("/api/v1/papers/upload-init", {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: {
        filename: name,
        title: "Evidence source versions",
        size_bytes: buffer.length,
        sha256: createHash("sha256").update(buffer).digest("hex"),
        paper_id: paperId ?? null,
      },
    });
    expect(initialized.status()).toBe(201);
    const file = (await initialized.json()).data;
    const sent = await page.request.post(file.upload_url, {
      headers,
      multipart: { file: { name, mimeType: "application/pdf", buffer } },
    });
    expect(sent.status()).toBe(200);
    const completed = await page.request.post(
      `/api/v1/papers/${file.paper_id}/upload-complete`,
      {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
        data: { upload_id: file.upload_id },
      },
    );
    expect(completed.status()).toBe(202);
    await expect
      .poll(
        async () =>
          (
            await read(
              `/papers/${file.paper_id}/parse-status?file_id=${file.paper_file_id}`,
            )
          ).parse_status,
        { timeout: 30000 },
      )
      .toBe("ready");
    return file;
  }
  return { headers, root, project, thread, create, read, upload, fixture };
}
type Attempt = {
  path: string;
  key: string | undefined;
  body: Record<string, any>;
};
function record(route: Route): Attempt {
  return {
    path: new URL(route.request().url()).pathname,
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
async function selectText(page: Page, value: string) {
  const text = page
    .locator(".textLayer span")
    .filter({ hasText: value })
    .first();
  await expect(text).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".pdf-loading")).toHaveCount(0);
  await text.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
  });
  await text.dispatchEvent("mouseup");
}
function editor(page: Page) {
  return page.getByRole("complementary", { name: "创建研究证据", exact: true });
}
async function openFile(page: Page, paperId: string, fileId: string) {
  const link = page.locator(`a[href="/papers/${paperId}?fileId=${fileId}"]`);
  if (!(await link.isVisible()))
    await page.getByText("文献元数据与文件版本", { exact: true }).click();
  await link.click();
}

test("lost evidence response keeps its file, page, target and key across project and file navigation", async ({
  page,
}) => {
  test.setTimeout(90000);
  const { project, thread, create, read, upload } = await account(page);
  for (let i = 0; i < 21; i++)
    await create(`/projects/${project.id}/threads`, {
      title: `Later question ${i}`,
      question: `Question ${i}`,
    });
  const otherProject = await create("/projects", { title: "另一课题" });
  const otherThread = await create(`/projects/${otherProject.id}/threads`, {
    title: "Other target",
    question: "Other question",
  });
  const first = await upload(1);
  const second = await upload(2, first.paper_id);
  const attempts: Attempt[] = [];
  await page.route("**/api/v1/threads/*/evidence", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts.push(record(route));
    if (attempts.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort("failed");
    } else await route.continue();
  });
  await page.goto(`/papers/${first.paper_id}?fileId=${first.paper_file_id}`);
  await selectText(page, ORIGINAL);
  const form = editor(page);
  await form
    .getByRole("button", { name: "加载更多阅读器研究线索", exact: true })
    .click();
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await form.getByLabel("我的理解").fill("原请求的解释");
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  await page.getByLabel("切换当前课题").selectOption(otherProject.id);
  await openFile(page, first.paper_id, second.paper_file_id);
  await selectText(page, REPLACEMENT);
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await selectText(page, "Replacement second page evidence.");
  await page.getByRole("button", { name: "放大", exact: true }).click();
  await expect(page.locator(".pdf-loading")).toHaveCount(0);
  await expect(form.getByLabel("原文摘录")).toHaveValue(ORIGINAL);
  await expect(form.getByLabel("我的理解")).toHaveValue("原请求的解释");
  await expect(form.getByLabel("关联研究线索")).toHaveValue(thread.id);
  await expect(form.getByLabel("关联研究线索")).toBeDisabled();
  await expect(form.getByLabel("摘录出处")).toContainText("文件 v1 · 第 1 页");
  await expect(form.getByRole("alert")).toBeVisible();
  await page.screenshot({
    path: "../artifacts/evidence-retry-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await form.scrollIntoViewIfNeeded();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../artifacts/evidence-retry-mobile.png",
    fullPage: true,
  });
  await form.getByRole("button", { name: "重试原请求", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("证据已保存");
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
  expect(attempts[0].path).toContain(`/threads/${thread.id}/evidence`);
  expect(attempts[0].body.paper_file_id).toBe(first.paper_file_id);
  expect(attempts[0].body.source.page_start).toBe(1);
  await expect(
    form.getByRole("link", { name: "回到研究线索 →", exact: true }),
  ).toHaveAttribute("href", `/threads/${thread.id}`);
  expect(await read(`/threads/${thread.id}/evidence`)).toHaveLength(1);
  expect(await read(`/threads/${otherThread.id}/evidence`)).toHaveLength(0);
});

test("an unconfirmed evidence request survives a different file address failing to load", async ({
  page,
}) => {
  const { thread, upload, read } = await account(page);
  const first = await upload(1);
  const second = await upload(2, first.paper_id);
  const attempts: Attempt[] = [];
  await page.route(`**/api/v1/threads/${thread.id}/evidence`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts.push(record(route));
    if (attempts.length === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort("failed");
    } else await route.continue();
  });
  let failAddress = true;
  await page.route(
    `**/api/v1/papers/${first.paper_id}/file?**`,
    async (route) => {
      if (
        failAddress &&
        new URL(route.request().url()).searchParams.get("file_id") ===
          second.paper_file_id
      )
        await unavailable(route, "新文件地址暂不可用");
      else await route.continue();
    },
  );
  await page.goto(`/papers/${first.paper_id}?fileId=${first.paper_file_id}`);
  await selectText(page, ORIGINAL);
  const form = editor(page);
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  await openFile(page, first.paper_id, second.paper_file_id);
  await expect(page.locator(".pdf-scroll").getByRole("alert")).toContainText(
    "新文件地址暂不可用",
  );
  await expect(form.getByLabel("原文摘录")).toHaveValue(ORIGINAL);
  await form.getByRole("button", { name: "重试原请求", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("证据已保存");
  expect(attempts[1]).toEqual(attempts[0]);
  expect((await read(`/threads/${thread.id}/evidence`))[0].paper_file_id).toBe(
    first.paper_file_id,
  );
  failAddress = false;
  await page
    .locator(".pdf-scroll")
    .getByRole("button", { name: "重试", exact: true })
    .click();
  await expect(page.locator(".textLayer")).toContainText(REPLACEMENT);
  await expect(
    form.getByRole("button", { name: "继续摘录下一条证据", exact: true }),
  ).toBeEnabled();
});

test("evidence precommit failure blocks duplicate submits and replays the original page after navigation", async ({
  page,
}) => {
  const { thread, upload, read } = await account(page);
  const file = await upload(1);
  const attempts: Attempt[] = [];
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/threads/${thread.id}/evidence`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts.push(record(route));
    if (attempts.length === 1) {
      await held;
      await unavailable(route, "证据暂时无法保存");
    } else await route.continue();
  });
  await page.goto(`/papers/${file.paper_id}`);
  await expect(page.locator(".textLayer")).toContainText(ORIGINAL);
  await expect(page.locator(".pdf-loading")).toHaveCount(0);
  const form = editor(page);
  await form.getByLabel("原文摘录").fill(ORIGINAL);
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect.poll(() => attempts.length).toBe(1);
  await form.locator("form").evaluate((element) => {
    if (!(element instanceof HTMLFormElement))
      throw new Error("Expected evidence form");
    element.requestSubmit();
    element.requestSubmit();
  });
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await selectText(page, SECOND);
  await expect(form.getByLabel("原文摘录")).toHaveValue(ORIGINAL);
  expect(attempts).toHaveLength(1);
  release();
  await expect(form.getByRole("alert")).toContainText("证据暂时无法保存");
  expect(await read(`/threads/${thread.id}/evidence`)).toHaveLength(0);
  await form.getByRole("button", { name: "重试原请求", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("页码级定位");
  expect(attempts[1]).toEqual(attempts[0]);
  const evidence = (await read(`/threads/${thread.id}/evidence`))[0];
  expect(evidence.page_start).toBe(1);
  expect(evidence.source_anchor.capture_method).toBe("manual");
});

test("editing a quote after turning the page preserves its origin until an explicit next excerpt", async ({
  page,
}) => {
  const { thread, upload, read } = await account(page);
  const file = await upload(1);
  const attempts: Attempt[] = [];
  await page.route(`**/api/v1/threads/${thread.id}/evidence`, async (route) => {
    if (route.request().method() === "POST") attempts.push(record(route));
    await route.continue();
  });
  await page.goto(`/papers/${file.paper_id}`);
  await selectText(page, ORIGINAL);
  const form = editor(page);
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.locator(".textLayer")).toContainText(SECOND);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  for (let index = 0; index < 4; index++) {
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await page.getByRole("button", { name: "放大", exact: true }).click();
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await page.getByRole("button", { name: "缩小", exact: true }).click();
  }
  await expect(page.locator(".textLayer")).toHaveText(SECOND);
  await expect(page.locator(".pdf-loading")).toHaveCount(0);
  expect(pageErrors).toEqual([]);
  await form
    .getByLabel("原文摘录")
    .fill("Original first page evidence. Manual clarification.");
  await expect(form.getByLabel("摘录出处")).toContainText("第 1 页 · 人工录入");
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("页码级定位");
  await form.locator("form").evaluate((element) => {
    if (!(element instanceof HTMLFormElement))
      throw new Error("Expected evidence form");
    element.requestSubmit();
  });
  expect(attempts).toHaveLength(1);
  await form
    .getByRole("button", { name: "继续摘录下一条证据", exact: true })
    .click();
  await expect(form.getByLabel("原文摘录")).toHaveValue("");
  await selectText(page, SECOND);
  await expect(form.getByLabel("摘录出处")).toContainText(
    "第 2 页 · 选中文本待校验",
  );
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("原文可定位");
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).not.toBe(attempts[1].key);
  expect(attempts.map((attempt) => attempt.body.source.page_start)).toEqual([
    1, 2,
  ]);
  const rows = await read(`/threads/${thread.id}/evidence`);
  expect(rows).toHaveLength(2);
  expect(
    rows.find((row: { page_start: number }) => row.page_start === 1).quote_text,
  ).toContain("Manual clarification");
});

test("publishing a new current PDF replaces the actual rendered text and retains an older draft", async ({
  page,
}) => {
  test.setTimeout(90000);
  const { thread, upload, read, fixture } = await account(page);
  const first = await upload(1);
  await page.goto(`/papers/${first.paper_id}`);
  await selectText(page, ORIGINAL);
  const form = editor(page);
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await form.getByLabel("我的理解").fill("旧版本的选择仍需保存");
  await page.getByLabel("选择 PDF 文件").setInputFiles(fixture(2));
  await expect
    .poll(
      async () => (await read(`/papers/${first.paper_id}/file`)).version_no,
      { timeout: 30000 },
    )
    .toBe(2);
  await expect(page.locator(".textLayer")).toContainText(REPLACEMENT, {
    timeout: 30000,
  });
  await expect(page.locator(".textLayer")).not.toContainText(ORIGINAL);
  await expect(form.getByLabel("原文摘录")).toHaveValue(ORIGINAL);
  await expect(form.getByLabel("摘录出处")).toContainText("文件 v1");
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("原文可定位");
  const second = await read(`/papers/${first.paper_id}/file`);
  expect(second.paper_file_id).not.toBe(first.paper_file_id);
  expect((await read(`/threads/${thread.id}/evidence`))[0].paper_file_id).toBe(
    first.paper_file_id,
  );
  await form
    .getByRole("button", { name: "继续摘录下一条证据", exact: true })
    .click();
  await selectText(page, REPLACEMENT);
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("原文可定位");
  const rows = await read(`/threads/${thread.id}/evidence`);
  expect(rows).toHaveLength(2);
  expect(
    rows.find((row: { quote_text: string }) => row.quote_text === REPLACEMENT)
      .paper_file_id,
  ).toBe(second.paper_file_id);
  await expect(page).toHaveURL(new RegExp(`/papers/${first.paper_id}$`));
});

test("a rejected blank evidence quote preserves editable input and corrects using the same key", async ({
  page,
}) => {
  const { thread, upload, read } = await account(page);
  const file = await upload(1);
  const attempts: Attempt[] = [];
  await page.route(`**/api/v1/threads/${thread.id}/evidence`, async (route) => {
    if (route.request().method() === "POST") attempts.push(record(route));
    await route.continue();
  });
  await page.goto(`/papers/${file.paper_id}`);
  await expect(page.locator(".textLayer")).toContainText(ORIGINAL);
  await expect(page.locator(".pdf-loading")).toHaveCount(0);
  const form = editor(page);
  await form.getByLabel("原文摘录").fill("   ");
  await form.getByLabel("我的理解").fill("失败后保留的理解");
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  await expect(form.getByLabel("原文摘录")).toBeEnabled();
  await expect(form.getByLabel("我的理解")).toHaveValue("失败后保留的理解");
  expect(await read(`/threads/${thread.id}/evidence`)).toHaveLength(0);
  await form.getByLabel("原文摘录").fill(ORIGINAL);
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("页码级定位");
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBe(attempts[1].key);
  expect((await read(`/threads/${thread.id}/evidence`))[0].interpretation).toBe(
    "失败后保留的理解",
  );
});

test("successful evidence receipt survives a failed file refresh and a read-only retry", async ({
  page,
}) => {
  const { thread, upload, read } = await account(page);
  const file = await upload(1);
  let failAddress = false,
    posts = 0;
  await page.route(`**/api/v1/papers/${file.paper_id}/file`, async (route) => {
    if (failAddress) await unavailable(route, "保存后文件读取失败");
    else await route.continue();
  });
  await page.route(`**/api/v1/threads/${thread.id}/evidence`, async (route) => {
    if (route.request().method() === "POST") {
      posts++;
      failAddress = true;
    }
    await route.continue();
  });
  await page.goto(`/papers/${file.paper_id}`);
  await selectText(page, ORIGINAL);
  const form = editor(page);
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await form.getByRole("button", { name: "保存研究证据", exact: true }).click();
  await expect(form.locator(".saved-evidence")).toContainText("原文可定位");
  await expect(page.locator(".pdf-scroll").getByRole("alert")).toContainText(
    "保存后文件读取失败",
  );
  await expect(form.getByLabel("原文摘录")).toBeDisabled();
  expect(posts).toBe(1);
  failAddress = false;
  await page
    .locator(".pdf-scroll")
    .getByRole("button", { name: "重试", exact: true })
    .click();
  await expect(page.locator(".textLayer")).toContainText(ORIGINAL);
  expect(posts).toBe(1);
  expect(await read(`/threads/${thread.id}/evidence`)).toHaveLength(1);
  await expect(form.locator(".saved-evidence")).toContainText("证据已保存");
});

test("a timed-out evidence response remains unconfirmed and cannot replay after the safe window", async ({
  page,
}) => {
  const { thread, upload, read } = await account(page);
  const file = await upload(1);
  let posts = 0,
    committed = false;
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/threads/${thread.id}/evidence`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    committed = true;
    await held;
    if (!route.request().failure()) await route.fulfill({ response });
  });
  await page.goto(`/papers/${file.paper_id}`);
  await selectText(page, ORIGINAL);
  const form = editor(page);
  await form.getByLabel("关联研究线索").selectOption(thread.id);
  await page.clock.install({ time: new Date() });
  try {
    await form
      .getByRole("button", { name: "保存研究证据", exact: true })
      .click();
    await expect.poll(() => committed).toBe(true);
    await page.clock.fastForward(31_000);
    await expect(form.getByRole("alert")).toContainText(
      "请求超时，结果尚未确认",
    );
    await expect(form.getByLabel("关联研究线索")).toBeDisabled();
    expect(await read(`/threads/${thread.id}/evidence`)).toHaveLength(1);
    await page.clock.setFixedTime(new Date(Date.now() + 24 * 60 * 60 * 1000));
    await form.getByRole("button", { name: "重试原请求", exact: true }).click();
    await expect(form.getByRole("alert")).toContainText(
      "原请求已超过可安全重试时限",
    );
    expect(posts).toBe(1);
  } finally {
    release();
  }
});

test("parse retries keep the original job after a lost response and require explicit intent for a later failure", async ({
  page,
}) => {
  test.setTimeout(60000);
  const { root, upload, read } = await account(page);
  const file = await upload(1);
  // Synthetic status failure; subsequent HTTP requests, broker delivery and PDF parsing are real.
  const baseline = failedParseFixture(root, file.paper_file_id, true);
  const requests: { key: string | undefined; job: string }[] = [];
  await page.route(
    `**/api/v1/papers/${file.paper_id}/files/${file.paper_file_id}/parse-retry`,
    async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      requests.push({
        key: route.request().headers()["idempotency-key"],
        job: (await response.json()).data.job_id,
      });
      if (requests.length === 1 || requests.length === 3)
        await route.abort("failed");
      else await route.fulfill({ response });
    },
  );
  await page.goto(`/papers/${file.paper_id}`);
  await page.getByText("文献元数据与文件版本", { exact: true }).click();
  const control = page.getByRole("region", {
    name: "解析重试状态",
    exact: true,
  });
  await control.getByRole("button", { name: "重试解析", exact: true }).click();
  await expect(control.getByRole("alert")).toBeVisible();
  await expect
    .poll(
      async () =>
        (
          await read(
            `/papers/${file.paper_id}/parse-status?file_id=${file.paper_file_id}`,
          )
        ).parse_status,
      { timeout: 30000 },
    )
    .toBe("ready");
  await control
    .getByRole("button", { name: "读取最新解析状态", exact: true })
    .click();
  await expect(
    control.getByText("当前文件状态：解析完成。", { exact: true }),
  ).toBeVisible();
  await control
    .getByRole("button", { name: "重试原解析请求", exact: true })
    .click();
  await expect(
    control.getByText("解析请求已接收，后台处理结果以文件状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
  expect(failedParseFixture(root, file.paper_file_id, true)).toBe(baseline + 1);
  await control
    .getByRole("button", { name: "读取最新解析状态", exact: true })
    .click();
  await control
    .getByRole("button", { name: "再次发起解析（新任务）", exact: true })
    .click();
  await expect(control.getByRole("alert")).toBeVisible();
  await expect(
    control.getByRole("button", {
      name: "再次发起解析（新任务）",
      exact: true,
    }),
  ).toHaveCount(0);
  await control
    .getByRole("button", { name: "重试原解析请求", exact: true })
    .click();
  await expect(
    control.getByText("解析请求已接收，后台处理结果以文件状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(requests).toHaveLength(4);
  expect(requests[3]).toEqual(requests[2]);
  expect(requests[0].key).not.toBe(requests[2].key);
  expect(requests[0].job).not.toBe(requests[2].job);
  expect(failedParseFixture(root, file.paper_file_id, false)).toBe(
    baseline + 2,
  );
});
