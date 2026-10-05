import { test, expect, type Browser, type Page } from "@playwright/test";

async function signIn(browser: Browser, role: "admin" | "member") {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/");
  await page
    .getByRole("button", {
      name:
        role === "admin"
          ? "Enter as demo administrator"
          : "Explore demo workspace",
    })
    .click();
  return page;
}

async function ask(page: Page, question: string) {
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByLabel("Ask a question").fill(question);
  await page.getByRole("button", { name: "Send question" }).click();
}

test("review is claimed, answered with a citation, published, and reused", async ({
  browser,
}) => {
  const question = "How many unused leave days carry over?";
  const note = "Browser review " + Date.now();
  const resolution = "Five days, used by March 31. " + note;

  const member = await signIn(browser, "member");
  await ask(member, question);
  await expect(
    member.getByText("Covered by approved policy").first(),
  ).toBeVisible();
  await member
    .getByRole("button", { name: "Request human review" })
    .last()
    .click();
  await member.getByLabel("Additional context").fill(note);
  await member.getByRole("button", { name: "Submit for review" }).click();

  const admin = await signIn(browser, "admin");
  await admin
    .getByRole("button", { name: "Review queue", exact: true })
    .click();
  const card = admin.locator(".review-card").filter({ hasText: note });
  await card.getByRole("button", { name: "Claim" }).click();
  await expect(card.getByText("In review")).toBeVisible();
  await card.getByLabel("Answer or reason").fill(resolution);
  await card.getByRole("checkbox", { name: /Carryover/ }).check();
  await card.getByRole("checkbox", { name: /Share this answer/ }).check();
  await card.getByRole("button", { name: "Publish answer" }).click();
  await expect(card.getByText("Answered")).toBeVisible();

  await member
    .getByRole("button", { name: "Review queue", exact: true })
    .click();
  const mine = member.locator(".review-card").filter({ hasText: note });
  await expect(
    mine.locator(".review-resolution").getByText(resolution),
  ).toBeVisible();
  await expect(mine.getByText(/Time off, Carryover/)).toBeVisible();

  const colleague = await signIn(browser, "member");
  await ask(colleague, question);
  await expect(colleague.getByText("REVIEWED ANSWER").first()).toBeVisible();
  await expect(colleague.getByText(resolution).first()).toBeVisible();
});

test("conflicting policies are flagged until an administrator sets precedence", async ({
  browser,
}) => {
  const admin = await signIn(browser, "admin");
  await ask(admin, "Is the meal allowance $75 or $90?");
  await expect(admin.getByText("Policies conflict").last()).toBeVisible();
  await admin.getByRole("radio", { name: "Travel and expenses" }).check();
  await admin
    .getByLabel("Reason, shown to readers")
    .fill("Finance sets allowances.");
  await admin.getByRole("button", { name: "Save precedence" }).click();

  await ask(admin, "Is the meal allowance $75 or $90?");
  await expect(
    admin.getByText(
      "Travel and expenses takes precedence for Meal reimbursement: Finance sets allowances.",
    ),
  ).toBeVisible();

  await admin.getByRole("button", { name: "Documents", exact: true }).click();
  const rule = admin
    .locator(".precedence-row")
    .filter({ hasText: "Finance sets allowances." });
  await rule.getByRole("button", { name: "Remove" }).click();
  await expect(rule).toHaveCount(0);
});

test("a citation opens in its section with pinpoint provenance", async ({
  browser,
}) => {
  const member = await signIn(browser, "member");
  await ask(member, "Who approves annual leave?");
  await member.locator(".citation").first().click();
  await expect(member.locator(".pinpoint")).toContainText("paragraph");
  await expect(member.locator(".section-text .cited")).toBeVisible();
  await expect(member.locator(".provenance")).toContainText(
    "People Operations",
  );
});

test("an administrator compares two versions section by section", async ({
  browser,
}) => {
  const admin = await signIn(browser, "admin");
  await admin.getByRole("button", { name: "Documents", exact: true }).click();
  const name = "Compare-" + Date.now() + ".md";
  await admin.getByLabel("Upload document file").setInputFiles({
    name,
    mimeType: "text/markdown",
    buffer: Buffer.from("# Rules\n## Kept\nSame.\n## Edited\nOld rule."),
  });
  const row = admin.locator(".document-row").filter({ hasText: name });
  await expect(row.getByText("Ready", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await admin
    .getByRole("button", { name: "Replace " + name, exact: true })
    .click();
  await admin.getByLabel("Upload document file").setInputFiles({
    name,
    mimeType: "text/markdown",
    buffer: Buffer.from("# Rules\n## Kept\nSame.\n## Edited\nNew rule."),
  });
  await expect(row.getByText("v2", { exact: true })).toBeVisible();
  await expect(row.getByText("Ready", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await row.getByRole("button", { name: "Compare with previous" }).click();
  const diff = admin.getByLabel("Version comparison");
  await expect(diff).toContainText("1 of 2 sections changed");
  await expect(diff.locator("del")).toHaveText("Old rule.");
  await expect(diff.locator("ins")).toHaveText("New rule.");
  await admin
    .getByRole("button", { name: "Delete " + name, exact: true })
    .click();
  await admin.getByRole("button", { name: "Confirm delete" }).click();
});
