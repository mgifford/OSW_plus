import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const PAGES = [
  { name: "homepage", path: "/" },
  { name: "events page", path: "/events.html" },
  { name: "calendar view", path: "/calendar-view.html" },
  { name: "places map", path: "/places-map.html" },
  { name: "2025 resources", path: "/2025-resources.html" },
  // Generated knowledge-platform pages (produced by generate_knowledge_site.py)
  { name: "knowledge hub", path: "/explore.html" },
  { name: "knowledge search", path: "/knowledge-search.html" },
  { name: "relationship map", path: "/graph.html" },
  { name: "reports index", path: "/reports/index.html" },
  { name: "annual briefing", path: "/reports/unosw/2025.html" },
  { name: "theme briefing", path: "/reports/unosw/themes/ai.html" },
  { name: "organizations directory", path: "/reports/unosw/organizations.html" },
  { name: "people directory", path: "/reports/unosw/people.html" },
  { name: "repos & standards index", path: "/reports/unosw/repositories-and-standards.html" },
  { name: "timeline", path: "/timeline.html" },
  { name: "year hub", path: "/unosw/2025/explore.html" },
  { name: "speaker profile", path: "/unosw/2025/speakers/sachiko-muto.html" },
  { name: "session page", path: "/unosw/2025/sessions/sess-opening-plenary.html" },
  { name: "organization profile", path: "/unosw/2025/organizations/un-odet.html" },
  { name: "2026 year hub", path: "/unosw/2026/explore.html" },
  { name: "2026 session page", path: "/unosw/2026/sessions/sess-2026-016.html" },
  { name: "2024 year hub", path: "/unosw/2024/explore.html" },
  { name: "2024 session page", path: "/unosw/2024/sessions/sess-2024-d1-opening-plenary.html" },
];

async function scanPage(page, path) {
  await page.goto(path);
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
    expect(results.violations, `Accessibility violations found on ${path}:\n\n${summary}`).toHaveLength(0);
  }

  return results;
}

test.describe("Accessibility — WCAG 2.2 AA", () => {
  for (const pageConfig of PAGES) {
    test(`${pageConfig.name} has no WCAG 2.2 AA violations`, async ({ page }) => {
      await scanPage(page, pageConfig.path);
    });
  }

  test("homepage has a skip navigation link", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const skipLink = page.locator('a[href="#main-content"]');
    await expect(skipLink).toHaveCount(1);
  });

  test("homepage has proper heading hierarchy", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.locator("h1")).toHaveCount(1);

    const headings = page.locator("h1, h2, h3, h4, h5, h6");
    const count = await headings.count();
    expect(count).toBeGreaterThan(1);

    const firstTag = await headings.first().evaluate((el) => el.tagName.toLowerCase());
    expect(firstTag).toBe("h1");
  });

  test("homepage has alt text on images", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const imagesWithoutAlt = page.locator("img:not([alt])");
    await expect(imagesWithoutAlt).toHaveCount(0);
  });

  test("homepage interactive links are keyboard focusable", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const links = page.locator("a[href]");
    const count = await links.count();

    for (let i = 0; i < count; i++) {
      const tabIndex = await links.nth(i).evaluate((el) => el.tabIndex);
      expect(tabIndex).toBeGreaterThanOrEqual(0);
    }
  });

  test("homepage lang attribute is set", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBeTruthy();
  });
});
