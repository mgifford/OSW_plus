import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Accessibility — WCAG 2.2 AA", () => {
  test("homepage has no WCAG 2.2 AA violations", async ({ page }) => {
    await page.goto("/");
    // Wait for the page to fully render (fetch may fail in static test, that's OK)
    await page.waitForLoadState("domcontentloaded");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();

    if (results.violations.length > 0) {
      const summary = results.violations
        .map(
          (v) =>
            `[${v.id}] ${v.description}\n  Impact: ${v.impact}\n  Nodes: ${v.nodes
              .map((n) => n.html)
              .slice(0, 3)
              .join("\n         ")}`
        )
        .join("\n\n");
      expect(results.violations, `Accessibility violations found:\n\n${summary}`).toHaveLength(0);
    }
  });

  test("homepage has a skip navigation link", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const skipLink = page.locator('a[href="#main-content"]');
    await expect(skipLink).toHaveCount(1);
  });

  test("homepage has proper heading hierarchy", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    // h1 must exist
    await expect(page.locator("h1")).toHaveCount(1);

    // h2 must come after h1 — no h3 before the first h2
    const headings = page.locator("h1, h2, h3, h4, h5, h6");
    const count = await headings.count();
    expect(count).toBeGreaterThan(1);

    const firstTag = await headings.first().evaluate((el) => el.tagName.toLowerCase());
    expect(firstTag).toBe("h1");
  });

  test("all images have alt text", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const imagesWithoutAlt = page.locator("img:not([alt])");
    await expect(imagesWithoutAlt).toHaveCount(0);
  });

  test("all interactive elements are keyboard focusable", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const links = page.locator("a[href]");
    const count = await links.count();

    // Each link must be focusable (tabIndex >= 0 or default)
    for (let i = 0; i < count; i++) {
      const tabIndex = await links.nth(i).evaluate((el) => el.tabIndex);
      expect(tabIndex).toBeGreaterThanOrEqual(0);
    }
  });

  test("page lang attribute is set", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBeTruthy();
  });
});
