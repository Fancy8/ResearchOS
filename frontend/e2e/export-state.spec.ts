import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { createHash } from "node:crypto";

test.setTimeout(60000);
const root = path.resolve(process.cwd(), "..");
const python = path.join(root, "runtime/venv/Scripts/python.exe");
const control = (page: Page) => page.locator(".export-card");
function jobFixture(id: string, status: "failed" | "expire") {
  execFileSync(
    python,
    [
      "-c",
      `import sys,psycopg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
v=dotenv_values('.env');u=make_url(v['RESEARCHOS_ADMIN_DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
with psycopg.connect(u,autocommit=True) as db:
    if sys.argv[2]=='failed':r=db.execute("UPDATE export_jobs SET status='failed',error_code='EXPORT_SOURCE_HASH_MISMATCH' WHERE id=%s AND status='succeeded'",(sys.argv[1],))
    else:r=db.execute("UPDATE export_jobs SET expires_at=now()-interval '1 second' WHERE id=%s AND status='succeeded'",(sys.argv[1],))
    assert r.rowcount==1`,
      id,
      status,
    ],
    { cwd: root },
  );
}
async function account(page: Page) {
  const email = `export-${crypto.randomUUID()}@example.com`;
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
          password: "ResearchOS-export-state-2026",
          display_name: "导出恢复验收",
          invitation_token: invitation,
        },
      })
    ).status(),
  ).toBe(201);
  const login = await page.request.post("/api/v1/auth/login", {
    headers: origin,
    data: { email, password: "ResearchOS-export-state-2026" },
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
          project_title: "导出恢复课题",
          question: "Export recovery question",
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
  const me = await read("/me");
  const key = `researchos.${me.workspace_id}.export`;
  const journal = () =>
    page.evaluate((key) => {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    }, key);
  async function ready(id: string) {
    await expect
      .poll(async () => (await read(`/exports/${id}`)).status, {
        timeout: 30000,
      })
      .toBe("succeeded");
  }
  await page.goto("/settings/data");
  await expect(
    control(page).getByRole("button", { name: "创建导出档案", exact: true }),
  ).toBeEnabled();
  return { headers, read, journal, key, ready, workspaceId: me.workspace_id };
}

async function uploadPaper(
  page: Page,
  headers: Record<string, string>,
  read: (endpoint: string) => Promise<any>,
) {
  const pdf = path.join(
    root,
    `artifacts/fixtures/export-${crypto.randomUUID()}.pdf`,
  );
  execFileSync(
    python,
    [
      "-c",
      `from pathlib import Path
from reportlab.pdfgen import canvas
import sys
p=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True)
c=canvas.Canvas(str(p));c.drawString(60,720,'Export download source bytes');c.showPage();c.save()`,
      pdf,
    ],
    { cwd: root },
  );
  const buffer = fs.readFileSync(pdf);
  const hash = createHash("sha256").update(buffer).digest("hex");
  const initResponse = await page.request.post("/api/v1/papers/upload-init", {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      filename: path.basename(pdf),
      size_bytes: buffer.length,
      sha256: hash,
    },
  });
  expect(initResponse.status()).toBe(201);
  const file = (await initResponse.json()).data;
  expect(
    (
      await page.request.post(file.upload_url, {
        headers,
        multipart: {
          file: {
            name: path.basename(pdf),
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
  return { file, hash };
}

test("lost export receipt replays the same job even after the original archive has finished", async ({
  page,
}) => {
  const { read, ready } = await account(page);
  const requests: { key?: string; job: string; body: object }[] = [];
  await page.route("**/api/v1/exports", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    requests.push({
      key: route.request().headers()["idempotency-key"],
      job: (await response.json()).data.id,
      body: route.request().postDataJSON(),
    });
    if (requests.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toBeVisible();
  await ready(requests[0].job);
  const retry = control(page).getByRole("button", {
    name: /^(创建导出档案|重试原导出请求)$/,
  });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toEqual(requests[0]);
  expect(await read("/exports")).toHaveLength(1);
  await expect(
    control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
});

test("unknown export survives reload with frozen original options", async ({
  page,
}) => {
  const { journal, ready, read } = await account(page);
  const requests: { key?: string; job: string; body: object }[] = [];
  await page.route("**/api/v1/exports", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    requests.push({
      key: route.request().headers()["idempotency-key"],
      job: (await response.json()).data.id,
      body: route.request().postDataJSON(),
    });
    if (requests.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await control(page).getByRole("checkbox").uncheck();
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toBeVisible();
  const original = await journal();
  expect(original.phase).toBe("unknown");
  expect(original.includeFiles).toBe(false);
  await ready(requests[0].job);
  await page.reload();
  await expect(control(page).getByRole("checkbox")).not.toBeChecked();
  await expect(control(page).getByRole("checkbox")).toBeDisabled();
  await control(page)
    .getByRole("button", { name: "重试原导出请求", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
  const accepted = await journal();
  expect(accepted.key).toBe(original.key);
  expect(accepted.jobId).toBe(requests[0].job);
  expect(Object.keys(accepted).sort()).toEqual(
    [
      "version",
      "workspaceId",
      "key",
      "createdAt",
      "includeFiles",
      "phase",
      "jobId",
    ].sort(),
  );
  expect(await read("/exports")).toHaveLength(1);
});

test("synchronous double click and another tab share one export intent", async ({
  page,
  context,
}) => {
  const { read } = await account(page);
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let posts = 0;
  await page.route("**/api/v1/exports", async (route) => {
    posts++;
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    await barrier;
    await route.fulfill({ response });
  });
  const second = await context.newPage();
  try {
    await control(page)
      .getByRole("button", { name: "创建导出档案", exact: true })
      .evaluate((button: HTMLButtonElement) => {
        button.click();
        button.click();
      });
    await expect.poll(() => posts).toBe(1);
    await second.goto("/settings/data");
    await control(second)
      .getByRole("button", { name: "重试原导出请求", exact: true })
      .click();
    await expect(control(second).getByRole("alert")).toContainText(
      "另一个标签页正在处理导出请求",
    );
    expect(posts).toBe(1);
    release();
    await expect(
      control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      control(second).getByText(
        "导出请求已接收，后台处理结果以任务状态为准。",
        { exact: true },
      ),
    ).toBeVisible();
    expect(await read("/exports")).toHaveLength(1);
    expect(posts).toBe(1);
  } finally {
    release();
    await second.close();
  }
});

test("precommit failure retains the key and original options for an explicit retry", async ({
  page,
}) => {
  const { journal, read } = await account(page);
  const keys: (string | undefined)[] = [];
  await page.route("**/api/v1/exports", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1)
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "TEST_UNAVAILABLE", message: "验收：提交前暂不可用" },
        }),
      });
    else await route.fulfill({ response: await route.fetch() });
  });
  await control(page).getByRole("checkbox").uncheck();
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "提交前暂不可用",
  );
  expect(await read("/exports")).toHaveLength(0);
  const original = await journal();
  await expect(control(page).getByRole("checkbox")).toBeDisabled();
  await control(page)
    .getByRole("button", { name: "重试原导出请求", exact: true })
    .click();
  await expect(
    control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(keys).toEqual([original.key, original.key]);
  expect((await read("/exports"))[0].include_files).toBe(false);
});

test("confirmed export survives detail and list failures without another POST", async ({
  page,
}) => {
  const { journal, ready } = await account(page);
  let posts = 0;
  let jobId = "";
  await page.route("**/api/v1/exports**", async (route) => {
    if (route.request().method() === "POST") {
      posts++;
      const response = await route.fetch();
      jobId = (await response.json()).data.id;
      await route.fulfill({ response });
    } else
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "TEST_READ_FAILED",
            message: "验收：导出读取暂不可用",
          },
        }),
      });
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    control(page).getByText(
      "原请求已接收，状态读取暂未完成。重读不会创建新任务。",
      { exact: true },
    ),
  ).toBeVisible();
  await control(page)
    .getByRole("button", { name: "读取原导出状态", exact: true })
    .click();
  await expect(
    control(page).getByText("读取暂未完成，原导出请求仍保留。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(posts).toBe(1);
  expect((await journal()).phase).toBe("accepted");
  await page.unroute("**/api/v1/exports**");
  await ready(jobId);
  await control(page)
    .getByRole("button", { name: "读取原导出状态", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("unwritable journal prevents mutation and repaired storage allows explicit submission", async ({
  page,
}) => {
  const { key, read } = await account(page);
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/exports"
    )
      posts++;
  });
  await page.evaluate((key) => {
    const original = Storage.prototype.setItem;
    (
      window as unknown as { restoreExportStorage: () => void }
    ).restoreExportStorage = () => {
      Storage.prototype.setItem = original;
    };
    Storage.prototype.setItem = function (k, value) {
      if (k === key)
        throw new DOMException("fixture quota", "QuotaExceededError");
      return original.call(this, k, value);
    };
  }, key);
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "无法保存本机导出恢复记录",
  );
  expect(posts).toBe(0);
  expect(await read("/exports")).toHaveLength(0);
  await page.evaluate(() =>
    (
      window as unknown as { restoreExportStorage: () => void }
    ).restoreExportStorage(),
  );
  await control(page)
    .getByRole("button", { name: "重新读取恢复记录", exact: true })
    .click();
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("known success survives receipt storage failure and readonly recovery repairs it", async ({
  page,
}) => {
  const { key, journal, ready } = await account(page);
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/exports"
    )
      posts++;
  });
  await page.evaluate((key) => {
    const original = Storage.prototype.setItem;
    (
      window as unknown as { restoreExportStorage: () => void }
    ).restoreExportStorage = () => {
      Storage.prototype.setItem = original;
    };
    Storage.prototype.setItem = function (k, value) {
      if (k === key && JSON.parse(value).phase === "accepted")
        throw new DOMException("fixture quota", "QuotaExceededError");
      return original.call(this, k, value);
    };
  }, key);
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(control(page).getByRole("alert")).toContainText(
    "无法保存本机导出恢复记录",
  );
  expect((await journal()).phase).toBe("unknown");
  await control(page)
    .getByRole("button", { name: "读取原导出状态", exact: true })
    .click();
  await expect(
    control(page).getByRole("button", { name: "重试原导出请求", exact: true }),
  ).toHaveCount(0);
  expect(posts).toBe(1);
  await page.evaluate(() =>
    (
      window as unknown as { restoreExportStorage: () => void }
    ).restoreExportStorage(),
  );
  await control(page)
    .getByRole("button", { name: "读取原导出状态", exact: true })
    .click();
  await expect.poll(async () => (await journal()).phase).toBe("accepted");
  const job = (await journal()).jobId;
  await ready(job);
  await page.reload();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("corrupt export journal blocks creation until explicitly acknowledged and cleared", async ({
  page,
}) => {
  const { key } = await account(page);
  await page.evaluate(
    (key) =>
      localStorage.setItem(
        key,
        '{"phase":"accepted","jobId":"not-a-uuid","download_url":"https://invalid.example"}',
      ),
    key,
  );
  await page.reload();
  await expect(control(page).getByRole("alert")).toContainText(
    "本机导出恢复记录无效",
  );
  await expect(
    control(page).getByRole("button", { name: "创建导出档案", exact: true }),
  ).toBeDisabled();
  await control(page)
    .getByText("管理本机导出恢复记录", { exact: true })
    .click();
  await control(page)
    .getByRole("button", { name: "已核对，清除本机导出恢复记录", exact: true })
    .click();
  await expect(
    control(page).getByRole("button", { name: "创建导出档案", exact: true }),
  ).toBeEnabled();
});

test("new export requires explicit intent and a successful fresh check of the original job", async ({
  page,
}) => {
  const { journal, ready, read } = await account(page);
  const requests: { key?: string; job: string; include: boolean }[] = [];
  await page.route("**/api/v1/exports", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    requests.push({
      key: route.request().headers()["idempotency-key"],
      job: (await response.json()).data.id,
      include: route.request().postDataJSON().include_files,
    });
    await route.fulfill({ response });
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const original = await journal();
  await ready(original.jobId);
  const pattern = `**/api/v1/exports/${original.jobId}`;
  await page.route(pattern, (route) => route.abort("failed"));
  await control(page)
    .getByRole("button", { name: "开始新的导出", exact: true })
    .click();
  await expect(
    control(page).getByText("读取暂未完成，原导出请求仍保留。", {
      exact: true,
    }),
  ).toBeVisible();
  expect((await journal()).key).toBe(original.key);
  expect(requests).toHaveLength(1);
  await page.unroute(pattern);
  await control(page)
    .getByRole("button", { name: "开始新的导出", exact: true })
    .click();
  await expect(control(page).getByRole("checkbox")).toBeEnabled();
  expect(await journal()).toBeNull();
  await control(page).getByRole("checkbox").uncheck();
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1].key).not.toBe(requests[0].key);
  expect(requests[1].job).not.toBe(requests[0].job);
  expect(requests.map((value) => value.include)).toEqual([true, false]);
  expect(await read("/exports")).toHaveLength(2);
});

test("explicit active-job rejection preserves its unused key for retry", async ({
  page,
}) => {
  const { journal, read } = await account(page);
  const keys: (string | undefined)[] = [];
  await page.route("**/api/v1/exports", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    // Synthetic HTTP rejection; its real transaction/rollback behavior is covered by PostgreSQL tests.
    if (keys.length === 1)
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "EXPORT_IN_PROGRESS",
            message: "已有导出任务，请等待它完成",
          },
        }),
      });
    else await route.fulfill({ response: await route.fetch() });
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText(
      "服务端未创建本次导出：已有另一项导出任务。可核对记录后重试原请求。",
      { exact: true },
    ),
  ).toBeVisible();
  const original = await journal();
  expect(original.phase).toBe("rejected");
  expect(await read("/exports")).toHaveLength(0);
  await control(page)
    .getByRole("button", { name: "重试原导出请求", exact: true })
    .click();
  await expect(
    control(page).getByText("导出请求已接收，后台处理结果以任务状态为准。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(keys).toEqual([original.key, original.key]);
  expect(await read("/exports")).toHaveLength(1);
});

test("failed and expired archives remain known outcomes and never silently restart", async ({
  page,
}) => {
  const { journal, ready, read } = await account(page);
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/exports"
    )
      posts++;
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const first = (await journal()).jobId;
  await ready(first);
  jobFixture(first, "failed");
  await control(page)
    .getByRole("button", { name: "读取原导出状态", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：失败。", { exact: true }),
  ).toBeVisible();
  await expect(control(page).getByText(/没有生成完整成功档案/)).toBeVisible();
  await expect(
    control(page).getByRole("button", { name: "下载 ZIP", exact: true }),
  ).toHaveCount(0);
  expect(posts).toBe(1);
  expect(
    (await page.request.get(`/api/v1/exports/${first}/download`)).status(),
  ).toBe(409);
  await control(page)
    .getByRole("button", { name: "开始新的导出", exact: true })
    .click();
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const second = (await journal()).jobId;
  await ready(second);
  jobFixture(second, "expire");
  await control(page)
    .getByRole("button", { name: "读取原导出状态", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已过期。", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".export-row")
      .filter({ hasText: "档案已过期。如需新的资料快照，请明确创建新导出。" }),
  ).toBeVisible();
  expect(
    (await page.request.get(`/api/v1/exports/${second}/download`)).status(),
  ).toBe(409);
  expect(posts).toBe(2);
  expect(await read("/exports")).toHaveLength(2);
  await page.screenshot({
    path: path.join(root, "artifacts/export-state-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(root, "artifacts/export-state-mobile.png"),
    fullPage: true,
  });
});

test("native ZIP download verifies actual PDF bytes and does not retry creation after a read failure", async ({
  page,
}) => {
  const { headers, read, ready, journal } = await account(page);
  const { file, hash } = await uploadPaper(page, headers, read);
  let posts = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/api/v1/exports"
    )
      posts++;
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const id = (await journal()).jobId;
  await ready(id);
  const pattern = `**/api/v1/exports/${id}`;
  await page.route(pattern, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "TEST_DOWNLOAD_READ",
          message: "验收：下载前读取不可用",
        },
      }),
    }),
  );
  await control(page)
    .getByRole("button", { name: "下载 ZIP", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "下载前读取不可用",
  );
  expect(posts).toBe(1);
  await page.unroute(pattern);
  const [download, response] = await Promise.all([
    page.waitForEvent("download"),
    page.waitForResponse(
      (r) => new URL(r.url()).pathname === `/api/v1/exports/${id}/download`,
    ),
    control(page)
      .getByRole("button", { name: "下载 ZIP", exact: true })
      .click(),
  ]);
  expect(response.status()).toBe(200);
  expect(await download.failure()).toBeNull();
  expect(
    path
      .resolve((await download.path())!)
      .toLowerCase()
      .startsWith(root.toLowerCase() + path.sep),
  ).toBe(true);
  const saved = path.join(root, `artifacts/downloads/export-${id}.zip`);
  await download.saveAs(saved);
  const downloadedHash = createHash("sha256")
    .update(fs.readFileSync(saved))
    .digest("hex");
  expect(downloadedHash).toBe(await response.headerValue("x-archive-sha256"));
  expect(downloadedHash).toBe((await read(`/exports/${id}`)).manifest_hash);
  execFileSync(
    python,
    [
      "-c",
      `import json,sys,hashlib
from zipfile import ZipFile
with ZipFile(sys.argv[1]) as z:
    m=json.loads(z.read('manifest.json'));assert m['schema_version']==1 and m['include_files'] is True
    assert len(m['files'])==1
    f=m['files'][0];assert f['paper_file_id']==sys.argv[2] and f['sha256']==sys.argv[3]
    assert hashlib.sha256(z.read(f['path'])).hexdigest()==sys.argv[3]
    assert b'password_hash' not in z.read('data/users.json')
    assert 'data/auth_sessions.json' not in z.namelist()`,
      saved,
      file.paper_file_id,
      hash,
    ],
    { cwd: root },
  );
  expect(posts).toBe(1);
  expect(await read("/exports")).toHaveLength(1);
});

test("late download precheck cannot navigate after logout", async ({
  page,
}) => {
  const { journal } = await account(page);
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const id = (await journal()).jobId;
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let finish!: () => void;
  const delivered = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let held = false;
  let downloads = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.endsWith(`/exports/${id}/download`))
      downloads++;
  });
  await page.route(`**/api/v1/exports/${id}`, async (route) => {
    const response = await route.fetch();
    held = true;
    await barrier;
    try {
      await route.fulfill({ response });
    } finally {
      finish();
    }
  });
  try {
    await control(page)
      .getByRole("button", { name: "下载 ZIP", exact: true })
      .click();
    await expect.poll(() => held).toBe(true);
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    release();
    await delivered;
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await expect(page).toHaveURL(/\/login$/);
    expect(downloads).toBe(0);
    expect(await journal()).toBeNull();
  } finally {
    release();
  }
});

test("expired replay window refuses another POST while preserving the original export intent", async ({
  page,
}) => {
  const { journal } = await account(page);
  let posts = 0;
  await page.route("**/api/v1/exports", async (route) => {
    posts++;
    await route.fetch();
    await route.abort("failed");
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toBeVisible();
  const original = await journal();
  await page.clock.setFixedTime(new Date(Date.now() + 24 * 60 * 60 * 1000));
  await control(page)
    .getByRole("button", { name: "重试原导出请求", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "原导出请求已超过可安全重试时限",
  );
  expect(posts).toBe(1);
  expect((await journal()).key).toBe(original.key);
});

test("logout clears unknown export metadata and ignores a late creation receipt", async ({
  page,
}) => {
  const { journal } = await account(page);
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let finish!: () => void;
  const delivered = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let committed = false;
  await page.route("**/api/v1/exports", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    committed = true;
    await barrier;
    try {
      await route.fulfill({ response });
    } finally {
      finish();
    }
  });
  try {
    await control(page)
      .getByRole("button", { name: "创建导出档案", exact: true })
      .click();
    await expect.poll(() => committed).toBe(true);
    expect((await journal()).phase).toBe("unknown");
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    release();
    await delivered;
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    expect(await journal()).toBeNull();
  } finally {
    release();
  }
});

test("explicit records-only fallback retains evidence when the original PDF is unavailable", async ({
  page,
}) => {
  const { headers, read, journal } = await account(page);
  const { file } = await uploadPaper(page, headers, read);
  const project = await read("/projects/current");
  const thread = (await read(`/projects/${project.id}/threads`))[0];
  const created = await page.request.post(
    `/api/v1/threads/${thread.id}/evidence`,
    {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: {
        paper_id: file.paper_id,
        paper_file_id: file.paper_file_id,
        quote_text: "Export download source bytes",
        interpretation: "Keep the original source relationship.",
        source: { page_start: 1, page_end: 1, capture_method: "selected" },
      },
    },
  );
  expect(created.status()).toBe(201);
  const evidence = (await created.json()).data;
  // Precise unavailability fixture; the worker's include/exclude handling is real.
  execFileSync(
    python,
    [
      "-c",
      `import sys,psycopg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
v=dotenv_values('.env');u=make_url(v['RESEARCHOS_ADMIN_DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
with psycopg.connect(u,autocommit=True) as db:
    r=db.execute("UPDATE paper_files SET availability_status='missing' WHERE id=%s AND upload_status='uploaded'",(sys.argv[1],));assert r.rowcount==1`,
      file.paper_file_id,
    ],
    { cwd: root },
  );
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：失败。", { exact: true }),
  ).toBeVisible();
  await expect(
    control(page).getByText(/可核对原件，或明确选择仅导出结构化记录/),
  ).toBeVisible();
  const fullId = (await journal()).jobId;
  expect(
    (await page.request.get(`/api/v1/exports/${fullId}/download`)).status(),
  ).toBe(409);
  await control(page)
    .getByRole("button", { name: "开始新的导出", exact: true })
    .click();
  await control(page).getByRole("checkbox").uncheck();
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const recordsId = (await journal()).jobId;
  expect(recordsId).not.toBe(fullId);
  expect((await journal()).includeFiles).toBe(false);
  const nextDownload = page.waitForEvent("download");
  await control(page)
    .getByRole("button", { name: "下载 ZIP", exact: true })
    .click();
  const download = await nextDownload;
  const saved = path.join(
    root,
    `artifacts/downloads/records-only-${recordsId}.zip`,
  );
  await download.saveAs(saved);
  expect(await download.failure()).toBeNull();
  execFileSync(
    python,
    [
      "-c",
      `import json,sys
from zipfile import ZipFile
with ZipFile(sys.argv[1]) as z:
    m=json.loads(z.read('manifest.json'));assert m['include_files'] is False and m['files']==[]
    assert m['missing_files']==[{'paper_file_id':sys.argv[2],'reason':'referenced_version_unavailable'}]
    e=json.loads(z.read('data/evidence.json'));assert e[0]['id']==sys.argv[3] and e[0]['paper_file_id']==sys.argv[2]
    f=json.loads(z.read('data/paper_files.json'));assert f[0]['availability_status']=='missing'
    assert not any(n.startswith('files/') for n in z.namelist())`,
      saved,
      file.paper_file_id,
      evidence.id,
    ],
    { cwd: root },
  );
  expect(await read("/exports")).toHaveLength(2);
});

test("binary download rejection stays in the application and preserves the known export", async ({
  page,
}) => {
  const { journal } = await account(page);
  let posts = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/api/v1/exports"
    )
      posts++;
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const original = await journal();
  await page.route(`**/api/v1/exports/${original.jobId}/download`, (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "EXPORT_UNAVAILABLE",
          message: "验收：档案在下载前刚刚过期",
        },
      }),
    }),
  );
  await control(page)
    .getByRole("button", { name: "下载 ZIP", exact: true })
    .click();
  await expect(control(page).getByRole("alert")).toContainText(
    "档案在下载前刚刚过期",
  );
  await expect(page).toHaveURL(/\/settings\/data$/);
  expect((await journal()).jobId).toBe(original.jobId);
  expect((await journal()).phase).toBe("accepted");
  expect(posts).toBe(1);
});

test("a cached job cannot authorize download for inconsistent restored options", async ({
  page,
  context,
}) => {
  const { key } = await account(page);
  let posts = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/api/v1/exports"
    )
      posts++;
  });
  await control(page)
    .getByRole("button", { name: "创建导出档案", exact: true })
    .click();
  await expect(
    control(page).getByText("原任务状态：已完成。", { exact: true }),
  ).toBeVisible();
  const second = await context.newPage();
  try {
    await second.goto("/settings/data");
    // Syntactically valid but semantically corrupted recovery metadata. The
    // server job and original browser cache still correctly say include_files=true.
    await second.evaluate((key) => {
      const value = JSON.parse(localStorage.getItem(key)!);
      value.includeFiles = false;
      localStorage.setItem(key, JSON.stringify(value));
    }, key);
    await expect(control(page).getByRole("checkbox")).not.toBeChecked();
    await expect(
      control(page).getByRole("button", { name: "下载 ZIP", exact: true }),
    ).toHaveCount(0);
    await control(page)
      .getByRole("button", { name: "读取原导出状态", exact: true })
      .click();
    await expect(control(page).getByRole("alert")).toContainText(
      "导出回执与原请求不一致",
    );
    expect(posts).toBe(1);
  } finally {
    await second.close();
  }
});
