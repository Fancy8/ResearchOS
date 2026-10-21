import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { createHash } from "node:crypto";

test.setTimeout(60000);
const root = path.resolve(process.cwd(), "..");
const python = path.join(root, "runtime/venv/Scripts/python.exe");
const control = (page: Page) =>
  page.getByRole("region", { name: "PDF 上传与恢复", exact: true });
async function forwardContent(page: Page, route: Route, fixture: string) {
  // Chromium interception omits file bytes in route.fetch(). Rebuild the test
  // proxy's multipart from the exact selected fixture. Unintercepted tests also
  // exercise the browser's native multipart path; final parsing verifies SHA-256.
  const response = await page.request.post(route.request().url(), {
    headers: {
      Origin: "http://localhost:3000",
      "X-CSRF-Token": route.request().headers()["x-csrf-token"],
    },
    multipart: {
      file: {
        name: path.basename(fixture),
        mimeType: "application/pdf",
        buffer: fs.readFileSync(fixture),
      },
    },
  });
  expect(response.status()).toBe(200);
  return response;
}
async function account(page: Page) {
  const id = crypto.randomUUID();
  const fixture = path.join(root, `artifacts/fixtures/upload-${id}.pdf`);
  execFileSync(
    python,
    [
      "-c",
      `from pathlib import Path
from reportlab.pdfgen import canvas
import sys
p=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True)
c=canvas.Canvas(str(p));c.drawString(60,720,sys.argv[2]);c.showPage();c.save()`,
      fixture,
      id,
    ],
    { cwd: root },
  );
  const email = `upload-${id}@example.com`;
  const invitation = execFileSync(
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
          password: "ResearchOS-upload-state-2026",
          display_name: "上传恢复验收",
          invitation_token: invitation,
        },
      })
    ).status(),
  ).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-upload-state-2026" },
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
          project_title: "原上传课题",
          question: "Upload recovery question",
          research_stage: "experimentation",
        },
      })
    ).status(),
  ).toBe(200);
  async function read(endpoint: string) {
    const r = await page.request.get(`/api/v1${endpoint}`);
    expect(r.status()).toBe(200);
    return (await r.json()).data;
  }
  const me = await read("/me");
  const project = await read("/projects/current");
  const key = `researchos.${me.workspace_id}.upload`;
  const journal = () =>
    page.evaluate((key) => {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    }, key);
  async function ready(file: { paper_id: string; paper_file_id: string }) {
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
  }
  async function uploadViaApi(paperId?: string) {
    const buffer = fs.readFileSync(fixture);
    const initialized = await page.request.post("/api/v1/papers/upload-init", {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: {
        filename: path.basename(fixture),
        size_bytes: buffer.length,
        sha256: createHash("sha256").update(buffer).digest("hex"),
        paper_id: paperId ?? null,
      },
    });
    expect(initialized.status()).toBe(201);
    const file = (await initialized.json()).data;
    expect(
      (
        await page.request.post(file.upload_url, {
          headers,
          multipart: {
            file: {
              name: path.basename(fixture),
              mimeType: "application/pdf",
              buffer,
            },
          },
        })
      ).status(),
    ).toBe(200);
    expect(
      (
        await page.request.post(
          `/api/v1/papers/${file.paper_id}/upload-complete`,
          {
            headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
            data: { upload_id: file.upload_id },
          },
        )
      ).status(),
    ).toBe(202);
    await ready(file);
    return file;
  }
  await page.goto("/library");
  await expect(
    control(page).getByRole("button", { name: "上传 PDF", exact: true }),
  ).toBeEnabled();
  return { fixture, key, project, journal, read, ready, headers, uploadViaApi };
}

test("lost initialization replays its key after reload and rejects a different PDF without retargeting", async ({
  page,
}) => {
  const { fixture, journal, project, read, ready, headers } =
    await account(page);
  const otherResponse = await page.request.post("/api/v1/projects", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { title: "另一个上传课题" },
  });
  expect(otherResponse.status()).toBe(201);
  const other = (await otherResponse.json()).data;
  const requests: { key?: string; body: unknown; ids: object }[] = [];
  await page.route("**/api/v1/papers/upload-init", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    requests.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
      ids: (await response.json()).data,
    });
    if (requests.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toBeVisible();
  const original = await journal();
  expect(original.phase).toBe("init");
  expect(original.projectId).toBe(project.id);
  await page.reload();
  await page
    .getByRole("combobox", { name: "切换当前课题", exact: true })
    .selectOption(other.id);
  await control(page)
    .getByLabel("选择 PDF 文件")
    .setInputFiles({
      name: "different.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-different"),
    });
  await expect(control(page).getByRole("alert")).toContainText(
    "与原上传摘要或大小不一致",
  );
  expect(requests).toHaveLength(1);
  expect((await journal()).id).toBe(original.id);
  await page.screenshot({
    path: path.join(root, "artifacts/upload-recovery-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(root, "artifacts/upload-recovery-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1366, height: 768 });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
  const accepted = await journal();
  expect(accepted.projectId).toBe(project.id);
  await ready(accepted.initialized);
  expect(await read("/papers")).toHaveLength(1);
  expect(Object.keys(accepted).sort()).toEqual(
    [
      "version",
      "workspaceId",
      "id",
      "createdAt",
      "phase",
      "name",
      "size",
      "sha256",
      "paperId",
      "projectId",
      "projectTitle",
      "initKey",
      "completeKey",
      "initialized",
      "receipt",
    ].sort(),
  );
});

test("lost content receipt retransmits identical bytes in the original session after reload", async ({
  page,
}) => {
  const { fixture, journal, ready, read } = await account(page);
  const ids: string[] = [];
  await page.route("**/api/v1/uploads/*/content", async (route) => {
    const response = await forwardContent(page, route, fixture);
    expect(response.status()).toBe(200);
    ids.push((await response.json()).data.upload_id);
    if (ids.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toContainText("文件传输中断");
  const original = await journal();
  expect(original.phase).toBe("transfer");
  expect(
    (await read(`/uploads/${original.initialized.upload_id}`)).status,
  ).toBe("pending");
  await page.reload();
  await control(page)
    .getByRole("button", { name: "继续原上传", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "重新选择原 PDF",
  );
  expect(ids).toHaveLength(1);
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  expect(ids).toEqual([
    original.initialized.upload_id,
    original.initialized.upload_id,
  ]);
  const accepted = await journal();
  expect(accepted.completeKey).toBe(original.completeKey);
  await ready(accepted.initialized);
  expect(
    await read(`/papers/${accepted.initialized.paper_id}/files`),
  ).toHaveLength(1);
});

test("lost completion recovers without File bytes and read errors never send another completion", async ({
  page,
}) => {
  const { fixture, journal, ready } = await account(page);
  const receipts: { key?: string; data: object }[] = [];
  await page.route("**/api/v1/papers/*/upload-complete", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    receipts.push({
      key: route.request().headers()["idempotency-key"],
      data: (await response.json()).data,
    });
    if (receipts.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toBeVisible();
  const original = await journal();
  expect(original.phase).toBe("complete");
  await ready(original.initialized);
  await page.reload();
  await control(page)
    .getByRole("button", { name: "继续原上传", exact: true })
    .click();
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  expect(receipts).toHaveLength(2);
  expect(receipts[1]).toEqual(receipts[0]);
  const routePattern = `**/api/v1/uploads/${original.initialized.upload_id}`;
  await page.route(routePattern, (route) => route.abort("failed"));
  await control(page)
    .getByRole("button", { name: "读取上传状态", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toBeVisible();
  expect((await journal()).phase).toBe("accepted");
  expect(receipts).toHaveLength(2);
  await page.unroute(routePattern);
  await control(page)
    .getByRole("button", { name: "读取上传状态", exact: true })
    .click();
  await expect(
    control(page).getByText(/上传：原件已接收；解析：解析完成/),
  ).toBeVisible();
  expect(receipts).toHaveLength(2);
});

test("malformed transfer response settles the controller and resumes the original upload", async ({
  page,
}) => {
  const { fixture, journal, ready } = await account(page);
  let count = 0;
  await page.route("**/api/v1/uploads/*/content", async (route) => {
    const response = await forwardContent(page, route, fixture);
    expect(response.status()).toBe(200);
    count++;
    if (count === 1)
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html>proxy receipt unavailable</html>",
      });
    else await route.fulfill({ response });
  });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toContainText(
    "传输回执无法确认",
  );
  const original = await journal();
  await control(page)
    .getByRole("button", { name: "继续原上传", exact: true })
    .click();
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  expect((await journal()).initialized).toEqual(original.initialized);
  expect(count).toBe(2);
  await ready(original.initialized);
});

test("two tabs serialize the same upload intent without duplicate initialization", async ({
  page,
  context,
}) => {
  const { fixture, journal } = await account(page);
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let inits = 0;
  await page.route("**/api/v1/papers/upload-init", async (route) => {
    inits++;
    const response = await route.fetch();
    await barrier;
    await route.fulfill({ response });
  });
  const second = await context.newPage();
  try {
    await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
    await expect.poll(() => inits).toBe(1);
    await second.goto("/library");
    await expect(
      control(second).getByRole("button", { name: "继续原上传", exact: true }),
    ).toBeEnabled();
    await control(second)
      .getByRole("button", { name: "继续原上传", exact: true })
      .click();
    await expect(control(second).getByRole("alert")).toContainText(
      "另一个标签页正在处理",
    );
    expect(inits).toBe(1);
    release();
    await expect(
      control(page).getByText("后台验证与解析已接收", { exact: true }),
    ).toBeVisible();
    await expect(
      control(second).getByText("后台验证与解析已接收", { exact: true }),
    ).toBeVisible();
    expect((await journal()).phase).toBe("accepted");
    expect(inits).toBe(1);
  } finally {
    release();
    await second.close();
  }
});

test("storage failure blocks mutations and a repaired store permits explicit selection", async ({
  page,
}) => {
  const { fixture, key } = await account(page);
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /upload-init|upload-complete|\/content$/.test(request.url())
    )
      posts++;
  });
  await page.evaluate((key) => {
    const original = Storage.prototype.setItem;
    (
      window as unknown as { restoreUploadStorage: () => void }
    ).restoreUploadStorage = () => {
      Storage.prototype.setItem = original;
    };
    Storage.prototype.setItem = function (k, value) {
      if (k === key)
        throw new DOMException("fixture quota", "QuotaExceededError");
      return original.call(this, k, value);
    };
  }, key);
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toContainText(
    "无法保存本地上传恢复记录",
  );
  expect(posts).toBe(0);
  await page.evaluate(() =>
    (
      window as unknown as { restoreUploadStorage: () => void }
    ).restoreUploadStorage(),
  );
  await control(page)
    .getByRole("button", { name: "重新读取恢复记录", exact: true })
    .click();
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(3);
});

test("corrupt journal fails closed and clearing it requires explicit acknowledgement", async ({
  page,
}) => {
  const { fixture, key } = await account(page);
  await page.evaluate(
    (key) =>
      localStorage.setItem(
        key,
        '{"phase":"init","upload_url":"https://invalid.example"}',
      ),
    key,
  );
  await page.reload();
  await expect(control(page).getByRole("alert")).toContainText("恢复记录无效");
  await expect(
    control(page).getByRole("button", { name: "上传 PDF", exact: true }),
  ).toBeDisabled();
  await control(page).getByText("管理本机恢复记录", { exact: true }).click();
  await control(page)
    .getByRole("button", { name: "已核对，清除本机恢复记录", exact: true })
    .click();
  await expect(
    control(page).getByRole("button", { name: "上传 PDF", exact: true }),
  ).toBeEnabled();
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
});

test("duplicate choice reuses the exact old version and independent copies require a new intent", async ({
  page,
}) => {
  const { fixture, uploadViaApi, journal, read } = await account(page);
  const first = await uploadViaApi();
  let inits = 0;
  await page.route("**/api/v1/papers/upload-init", async (route) => {
    inits++;
    await route.continue();
  });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(
    control(page).getByRole("button", { name: "复用此版本", exact: true }),
  ).toBeVisible();
  expect(inits).toBe(0);
  expect((await journal()).phase).toBe("duplicates");
  await control(page)
    .getByRole("button", { name: "复用此版本", exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/papers/${first.paper_id}\\?fileId=${first.paper_file_id}$`),
  );
  expect(await journal()).toBeNull();
  expect(inits).toBe(0);
  await page.goto("/library");
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await control(page)
    .getByRole("button", { name: "仍上传独立记录", exact: true })
    .click();
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  expect(inits).toBe(1);
  expect(await read("/papers")).toHaveLength(2);
});

test("expired original session is reported without silently allocating another upload", async ({
  page,
}) => {
  const { fixture, journal } = await account(page);
  let inits = 0;
  await page.route("**/api/v1/papers/upload-init", async (route) => {
    inits++;
    await route.continue();
  });
  await page.route("**/api/v1/uploads/*/content", (route) =>
    route.abort("failed"),
  );
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toBeVisible();
  const original = await journal();
  // Synthetic expiry for this test's upload only; HTTP, database and object handling remain real.
  execFileSync(
    python,
    [
      "-c",
      `import sys,psycopg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
v=dotenv_values('.env');u=make_url(v['RESEARCHOS_ADMIN_DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
with psycopg.connect(u,autocommit=True) as db:
    r=db.execute("UPDATE upload_sessions SET expires_at=now()-interval '1 minute' WHERE id=%s AND status='pending'",(sys.argv[1],));assert r.rowcount==1`,
      original.initialized.upload_id,
    ],
    { cwd: root },
  );
  await control(page)
    .getByRole("button", { name: "继续原上传", exact: true })
    .click();
  await expect(control(page).getByText(/原上传已过期/)).toBeVisible();
  expect(inits).toBe(1);
  expect((await journal()).id).toBe(original.id);
  expect((await journal()).phase).toBe("terminal");
});

test("a known completion survives receipt storage failure and readonly recovery repairs it", async ({
  page,
}) => {
  const { fixture, key, journal, ready } = await account(page);
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /upload-init|upload-complete|\/content$/.test(request.url())
    )
      posts++;
  });
  await page.evaluate((key) => {
    const original = Storage.prototype.setItem;
    (
      window as unknown as { restoreUploadStorage: () => void }
    ).restoreUploadStorage = () => {
      Storage.prototype.setItem = original;
    };
    Storage.prototype.setItem = function (k, value) {
      if (k === key && JSON.parse(value).phase === "accepted")
        throw new DOMException("fixture quota", "QuotaExceededError");
      return original.call(this, k, value);
    };
  }, key);
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  await expect(control(page).getByRole("alert")).toContainText(
    "无法保存本地上传恢复记录",
  );
  const original = await journal();
  expect(original.phase).toBe("complete");
  await ready(original.initialized);
  await control(page)
    .getByRole("button", { name: "读取上传状态", exact: true })
    .click();
  await expect(
    control(page).getByText(/上传：原件已接收；解析：解析完成/),
  ).toBeVisible();
  await expect(
    control(page).getByText("后台验证与解析已接收", { exact: true }),
  ).toBeVisible();
  await expect(
    control(page).getByRole("button", { name: "继续原上传", exact: true }),
  ).toHaveCount(0);
  expect(posts).toBe(3);
  await page.evaluate(() =>
    (
      window as unknown as { restoreUploadStorage: () => void }
    ).restoreUploadStorage(),
  );
  await control(page)
    .getByRole("button", { name: "读取上传状态", exact: true })
    .click();
  await expect.poll(async () => (await journal()).phase).toBe("accepted");
  await expect(control(page).getByRole("alert")).toHaveCount(0);
  expect(posts).toBe(3);
});

test("pausing an uncertain transfer keeps the original session for an explicit resume", async ({
  page,
}) => {
  const { fixture, journal, ready } = await account(page);
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let count = 0;
  await page.route("**/api/v1/uploads/*/content", async (route) => {
    const response = await forwardContent(page, route, fixture);
    count++;
    if (count === 1) await barrier;
    await route.fulfill({ response });
  });
  try {
    await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
    await expect.poll(() => count).toBe(1);
    const original = await journal();
    await control(page)
      .getByRole("button", { name: "暂停传输", exact: true })
      .click();
    await expect(control(page).getByRole("alert")).toContainText(
      "文件传输已暂停",
    );
    expect((await journal()).phase).toBe("transfer");
    release();
    await control(page)
      .getByRole("button", { name: "继续原上传", exact: true })
      .click();
    await expect(
      control(page).getByText("后台验证与解析已接收", { exact: true }),
    ).toBeVisible();
    expect((await journal()).initialized).toEqual(original.initialized);
    expect(count).toBe(2);
    await ready(original.initialized);
  } finally {
    release();
  }
});

test("an old unknown initialization cannot replay after the safe retention window", async ({
  page,
}) => {
  const { fixture, journal } = await account(page);
  let count = 0;
  await page.route("**/api/v1/papers/upload-init", async (route) => {
    count++;
    await route.fetch();
    await route.abort("failed");
  });
  await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
  await expect(control(page).getByRole("alert")).toBeVisible();
  const original = await journal();
  await page.clock.setFixedTime(new Date(Date.now() + 24 * 60 * 60 * 1000));
  await control(page)
    .getByRole("button", { name: "继续原上传", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "原请求已超过可安全重试时限",
  );
  expect(count).toBe(1);
  expect((await journal()).initKey).toBe(original.initKey);
});

test("logout clears upload metadata and a late initialization cannot recreate it", async ({
  page,
}) => {
  const { fixture, journal } = await account(page);
  let release!: () => void;
  let finished!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  const delivered = new Promise<void>((resolve) => {
    finished = resolve;
  });
  let committed = false;
  let transfers = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/uploads\/[^/]+\/content$/.test(new URL(request.url()).pathname)
    )
      transfers++;
  });
  await page.route("**/api/v1/papers/upload-init", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    committed = true;
    await barrier;
    try {
      await route.fulfill({ response });
    } finally {
      finished();
    }
  });
  try {
    await control(page).getByLabel("选择 PDF 文件").setInputFiles(fixture);
    await expect.poll(() => committed).toBe(true);
    expect((await journal()).phase).toBe("init");
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect(await journal()).toBeNull();
    release();
    await delivered;
    // Drain the returned fetch and React event work after the component unmount.
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    expect(await journal()).toBeNull();
    expect(transfers).toBe(0);
  } finally {
    release();
  }
});
