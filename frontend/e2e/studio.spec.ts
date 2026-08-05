import { expect, test } from "@playwright/test";

test("opens the core workstation views", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByText("选择一个音效项目")).toBeVisible();
  await page.getByRole("button", { name: "模型" }).click();
  await expect(page.getByRole("heading", { name: "模型与权重" })).toBeVisible();
  await expect(page.getByText("Woosh DFlow")).toBeVisible();
  await page.getByRole("button", { name: "设置" }).click();
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
  await expect(page.getByText("NVIDIA GeForce RTX 4060 Ti")).toBeVisible();
});
