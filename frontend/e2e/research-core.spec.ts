import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("real registration, onboarding, research hypothesis, decision and task", async ({
  page,
}) => {
  const root = path.resolve(process.cwd(), "..");
  const email = `e2e-${Date.now()}@example.com`;
  const invitation = execFileSync(
    path.join(root, "runtime/venv/Scripts/python.exe"),
    [path.join(root, "tools/invite.py"), email],
    { cwd: root, encoding: "utf-8" },
  ).trim();
  await page.goto("/login");
  await page.getByRole("button", { name: "有邀请码？创建账号" }).click();
  await page.getByLabel("你的称呼").fill("研究用户");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page
    .getByLabel("密码", { exact: true })
    .fill("ResearchOS-browser-2026");
  await page.getByLabel("邀请码").fill(invitation);
  await page.getByRole("button", { name: "创建空间", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "从你的第一个研究问题开始" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "开始设置" }).click();
  await page.getByLabel("课题名称").fill("浏览器端真实科研课题");
  await expect(
    page.getByText("草稿已保存，可随时继续", { exact: true }),
  ).toBeVisible();
  expect(
    (await (await page.request.get("/api/v1/projects")).json()).data,
  ).toEqual([]);
  const workspaceId = (await (await page.request.get("/api/v1/me")).json()).data
    .workspace_id;
  await page.evaluate(
    (id) => localStorage.removeItem(`researchos.${id}.onboarding`),
    workspaceId,
  );
  await page.reload();
  await page.getByRole("button", { name: "开始设置" }).click();
  await expect(page.getByLabel("课题名称")).toHaveValue("浏览器端真实科研课题");
  await page.getByLabel("首个研究问题").fill("查询决策价值如何影响任务分配？");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "浏览器端真实科研课题" }),
  ).toBeVisible();
  await page
    .getByRole("link")
    .filter({ hasText: "查询决策价值如何影响任务分配？" })
    .first()
    .click();
  await page.getByRole("button", { name: "+ 新增假设" }).click();
  await page
    .getByLabel("可进一步验证的研究判断")
    .fill("选择高价值查询可能改善完成率");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page
      .locator(".record-card p")
      .filter({ hasText: "选择高价值查询可能改善完成率" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "+ 记录判断" }).click();
  await page.getByLabel("决策标题").fill("开展等预算对照实验");
  await page
    .getByLabel("为什么采取这个决定？")
    .fill("需要验证收益是否来自预算差异");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "开展等预算对照实验", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "创建行动 →" }).click();
  await page.getByLabel("具体行动").fill("运行固定预算实验");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("运行固定预算实验")).toBeVisible();
  await page.getByRole("button", { name: "完成 运行固定预算实验" }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await page.screenshot({
    path: path.join(root, "artifacts/research-thread-desktop.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "开展等预算对照实验", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(
    page.getByRole("heading", { name: "回到你的研究" }),
  ).toBeVisible();
});
