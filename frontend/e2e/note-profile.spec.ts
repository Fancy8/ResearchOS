import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("note autosave, offline draft, retry and profile preferences", async ({
  page,
  context,
}) => {
  test.setTimeout(60000);
  const root = path.resolve(process.cwd(), "..");
  const email = `note-${Date.now()}@example.com`;
  const invitation = execFileSync(
    path.join(root, "runtime/venv/Scripts/python.exe"),
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  await page.goto("/login");
  await page.getByRole("button", { name: "有邀请码？创建账号" }).click();
  await page.getByLabel("你的称呼").fill("笔记研究者");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill("ResearchOS-notes-2026");
  await page.getByLabel("邀请码").fill(invitation);
  await page.getByRole("button", { name: "创建空间", exact: true }).click();
  await page.getByRole("button", { name: "开始设置" }).click();
  await page.getByLabel("课题名称").fill("笔记与偏好验证");
  await page.getByLabel("首个研究问题").fill("怎样保持研究记录可靠？");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("link", { name: "科研笔记", exact: true }).click();
  await page.getByRole("button", { name: "新建笔记" }).click();
  await page.getByLabel("笔记标题", { exact: true }).fill("自动保存验证");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  const editor = page.getByLabel("笔记正文");
  await editor.fill("服务器应保存这段真实输入。");
  await expect(page.locator(".note-save-state")).toContainText("已保存", {
    timeout: 5000,
  });
  await page.reload();
  await expect(page.getByLabel("笔记正文")).toContainText(
    "服务器应保存这段真实输入。",
  );
  await context.setOffline(true);
  await page.getByLabel("笔记正文").fill("断网期间必须保留这份草稿。");
  await expect(page.locator(".note-save-state")).toContainText("保存失败", {
    timeout: 5000,
  });
  await context.setOffline(false);
  await page.getByRole("button", { name: "立即保存", exact: true }).click();
  await expect(page.locator(".note-save-state")).toContainText("已保存");
  await page.reload();
  await expect(page.getByLabel("笔记正文")).toContainText(
    "断网期间必须保留这份草稿。",
  );
  await page.getByRole("button", { name: "公式", exact: true }).click();
  await page.getByLabel("LaTeX 公式").fill("\\frac{a}{b} + c^2");
  await page.getByLabel("公式类型").selectOption("block");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".katex")).toBeVisible();
  await expect(page.locator(".note-save-state")).toContainText("已保存");
  await page.reload();
  await expect(page.locator(".katex")).toBeVisible();
  const second = await context.newPage();
  await second.goto(page.url());
  await expect(second.getByLabel("笔记正文")).toContainText(
    "断网期间必须保留这份草稿。",
  );
  await page.getByLabel("笔记正文").fill("第一个页面的新版本。");
  await expect(page.locator(".note-save-state")).toContainText("已保存");
  await second.getByLabel("笔记正文").fill("第二个页面的冲突输入必须保留。");
  await expect(
    second.getByRole("heading", { name: "另一个页面修改了这份笔记" }),
  ).toBeVisible();
  await expect(second.getByLabel("笔记正文")).toContainText(
    "第二个页面的冲突输入必须保留。",
  );
  await second.getByRole("button", { name: "使用服务器内容" }).click();
  await expect(second.getByLabel("笔记正文")).toContainText(
    "第一个页面的新版本。",
  );
  await second.close();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "移入回收站", exact: true }).click();
  await page.getByRole("button", { name: "查看回收站" }).click();
  await expect(
    page.getByRole("heading", { name: "自动保存验证", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "恢复笔记" }).click();
  await page.getByRole("button", { name: "返回科研笔记" }).click();
  await page.getByRole("link", { name: "自动保存验证", exact: true }).click();
  await expect(page.getByLabel("笔记正文")).toContainText(
    "第一个页面的新版本。",
  );
  await page.getByRole("link", { name: "科研画像", exact: true }).click();
  await page.getByLabel("研究领域").fill("可靠的科研记录");
  await page
    .getByRole("checkbox", { name: "根据显式课题阶段调整首页模块顺序" })
    .uncheck();
  await page.getByRole("button", { name: "保存偏好" }).click();
  await expect(page.getByText("设置已保存")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("研究领域")).toHaveValue("可靠的科研记录");
  await page.screenshot({
    path: path.join(root, "artifacts/profile-desktop.png"),
    fullPage: true,
  });
});
