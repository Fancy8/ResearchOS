import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("PDF upload through real queue, text evidence, source jump and decision", async ({
  page,
}) => {
  test.setTimeout(90000);
  const root = path.resolve(process.cwd(), "..");
  const email = `pdf-${Date.now()}@example.com`;
  const python = path.join(root, "runtime/venv/Scripts/python.exe");
  execFileSync(python, [path.join(root, "tools/make_pdf_fixture.py")], {
    cwd: root,
  });
  const invitation = execFileSync(
    python,
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  await page.goto("/login");
  await page.getByRole("button", { name: "有邀请码？创建账号" }).click();
  await page.getByLabel("你的称呼").fill("PDF 研究者");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page
    .getByLabel("密码", { exact: true })
    .fill("ResearchOS-pdf-test-2026");
  await page.getByLabel("邀请码").fill(invitation);
  await page.getByRole("button", { name: "创建空间", exact: true }).click();
  await page.getByRole("button", { name: "开始设置" }).click();
  await page.getByLabel("课题名称").fill("PDF 证据链验证");
  await page.getByLabel("首个研究问题").fill("哪些原始证据支持研究判断？");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("link", { name: "文献库", exact: true }).click();
  await page
    .getByLabel("选择 PDF 文件")
    .setInputFiles(path.join(root, "artifacts/fixtures/evidence.pdf"));
  await expect(page.getByText("2 页", { exact: true })).toBeVisible({
    timeout: 30000,
  });
  await page.getByRole("link", { name: "evidence", exact: true }).click();
  const text = page
    .locator(".textLayer span")
    .filter({
      hasText: "Controlled experiment shows improved task completion.",
    })
    .first();
  await expect(text).toBeVisible({ timeout: 20000 });
  await text.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
  });
  await text.dispatchEvent("mouseup");
  await expect(page.getByLabel("原文摘录")).toHaveValue(
    "Controlled experiment shows improved task completion.",
  );
  await page
    .getByLabel("关联研究线索")
    .selectOption({ label: "哪些原始证据支持研究判断？" });
  await page.getByLabel("我的理解").fill("该结果只适用于报告的实验条件");
  await page.getByRole("button", { name: "保存研究证据" }).click();
  await expect(page.getByText("证据已保存 · 原文可定位")).toBeVisible();
  await page.getByRole("link", { name: "回到研究线索 →" }).click();
  await expect(page.locator(".evidence-card blockquote")).toHaveText(
    "Controlled experiment shows improved task completion.",
  );
  await page.getByRole("button", { name: "+ 新增假设" }).click();
  await page.getByLabel("可进一步验证的研究判断").fill("方法可能改善完成率");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "关联证据", exact: true }).click();
  await page.getByLabel("证据关系").selectOption("challenge");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "+ 记录判断" }).click();
  await page.getByLabel("决策标题").fill("继续对照验证");
  await page
    .getByLabel("为什么采取这个决定？")
    .fill("保留反面证据，检验方法是否稳定");
  await page
    .getByRole("checkbox", {
      name: "Controlled experiment shows improved task completion.",
    })
    .check();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "创建行动 →" }).click();
  await page.getByLabel("具体行动").fill("执行第二组对照");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "完成 执行第二组对照" }).click();
  await page.getByRole("link", { name: "回到原文", exact: true }).click();
  await expect(page.getByText("正在回看原始证据 · 第 1 页")).toBeVisible();
  await expect(
    page.getByText("已重新校验并高亮原文", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".source-highlight-layer span").first(),
  ).toBeVisible();
  const originalWidth = (await page
    .locator(".source-highlight-layer span")
    .first()
    .boundingBox())!.width;
  await page.getByRole("button", { name: "放大", exact: true }).click();
  await expect(page.getByText("125%", { exact: true })).toBeVisible();
  await expect
    .poll(
      async () =>
        ((
          await page
            .locator(".source-highlight-layer span")
            .first()
            .boundingBox()
        )?.width ?? 0) / originalWidth,
    )
    .toBeGreaterThan(1.2);
  await expect(page.locator(".pdf-loading")).toHaveCount(0);
  await page.screenshot({
    path: path.join(root, "artifacts/pdf-reader-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "设置与数据", exact: true }).click();
  await page.getByRole("button", { name: "创建导出档案" }).click();
  await expect(
    page
      .locator(".export-row")
      .getByRole("button", { name: "下载 ZIP", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  const download = page.waitForEvent("download");
  await page
    .locator(".export-row")
    .getByRole("button", { name: "下载 ZIP", exact: true })
    .click();
  await (
    await download
  ).saveAs(path.join(root, "artifacts/browser-research-archive.zip"));
});
