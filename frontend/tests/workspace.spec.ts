import { test, expect } from "@playwright/test";

test("member asks, opens a source, submits a review, and cannot upload", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore demo workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Answers you can trace." }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: /What is the home office equipment allowance/,
    })
    .click();
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(
    page.getByText("Covered by approved policy").first(),
  ).toBeVisible();
  await page.locator(".citation").first().click();
  await expect(page.getByText("Access checked when opened")).toBeVisible();
  await page.getByRole("button", { name: "Request human review" }).click();
  await page
    .getByLabel("Additional context")
    .fill("Please clarify contractor eligibility.");
  await page.getByRole("button", { name: "Submit for review" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Review queue", exact: true }).click();
  await expect(
    page.getByText("Please clarify contractor eligibility.").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Upload document", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByText("Local evidence extraction")).toBeVisible();
});

test("admin uploads, ingests, asks, replaces, and deletes", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Enter as demo administrator" })
    .click();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  const name = "Browser-policy-" + Date.now() + ".txt";
  const marker = "browserorchid" + Date.now();
  await page.getByLabel("Upload document file").setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: Buffer.from(marker + " allowance is 42 credits."),
  });
  const row = page.locator(".document-row").filter({ hasText: name });
  await expect(row.getByText("Ready", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByLabel("Ask a question").fill(marker);
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(
    page.getByText(marker + " allowance is 42 credits."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await page
    .getByRole("button", { name: "Replace " + name, exact: true })
    .click();
  await page.getByLabel("Upload document file").setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: Buffer.from(marker + " allowance is 84 credits."),
  });
  await expect(row.getByText("v2", { exact: true })).toBeVisible();
  await expect(row.getByText("Ready", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByLabel("Ask a question").fill(marker);
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(
    page.getByText(marker + " allowance is 84 credits."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await page
    .getByRole("button", { name: "Delete " + name, exact: true })
    .click();
  await page.getByRole("button", { name: "Confirm delete" }).click();
  await expect(row).toHaveCount(0);
});

test("narrow screen navigation and no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Explore demo workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Answers you can trace." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/mobile-documents.png",
    fullPage: true,
    animations: "disabled",
  });
});

test("desktop appearance and keyboard question submission", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "Explore demo workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Answers you can trace." }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/desktop-ask.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByLabel("Ask a question").fill("unknownzebrapolicy");
  await page.getByLabel("Ask a question").press("Enter");
  await expect(
    page.getByText("Not covered by approved policy").first(),
  ).toBeVisible();
});
