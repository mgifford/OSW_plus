import { test, expect } from "@playwright/test";

// nav.js reads window.__NAV_NOW (if set) instead of the real clock, so we can
// exercise both sides of the event-submission window deterministically.
// Configured event end is 2026-06-26, so the window is 2026-01-01 .. 2026-07-03.

test.describe("Event submission window", () => {
  test("outside the window: submit CTAs are disabled", async ({ page }) => {
    await page.addInitScript(() => { window.__NAV_NOW = "2026-09-01"; });
    await page.goto("/index.html");
    await page.waitForLoadState("networkidle");

    // The nav CTA becomes a non-link "closed" chip.
    await expect(page.locator(".site-nav-submit.submit-closed")).toHaveCount(1);
    await expect(page.locator('a.site-nav-submit[href*="submit-event.yml"]')).toHaveCount(0);

    // No un-gated event-submission link remains anywhere on the page.
    await expect(page.locator('a[href*="submit-event.yml"]:not([data-submit-gated])')).toHaveCount(0);
    // At least one in-page submit link was gated (the static quick-action card).
    await expect(page.locator('a[href*="submit-event.yml"].submit-closed').first()).toBeVisible();
  });

  test("inside the window: submit CTA is a live link", async ({ page }) => {
    await page.addInitScript(() => { window.__NAV_NOW = "2026-03-15"; });
    await page.goto("/index.html");
    await page.waitForLoadState("networkidle");

    await expect(page.locator('a.site-nav-submit[href*="submit-event.yml"]')).toHaveCount(1);
    await expect(page.locator(".site-nav-submit.submit-closed")).toHaveCount(0);
  });
});
