import { test, expect } from '@playwright/test';

/**
 * End-to-end workflow loop test.
 *
 * Walks the primary TradeCraft workflow:
 *   Command Center -> Sectors -> save hypothesis -> hypotheses page ->
 *   Terminal banner -> Command Center backlog -> Strategy Lab -> deploy ->
 *   Coach badge.
 *
 * Requires the full live stack (FastAPI backend on :8000 + Postgres on :5431)
 * to be running, since every step proxies to `/api/*`. See playwright.config.ts
 * for the webServer that boots the Vite frontend.
 *
 * NOTE: the `/` route renders <CommandCenter /> WITHOUT the shared <Layout />,
 * so the TerminalHypothesisBanner (mounted in Layout's TerminalHost) is NOT
 * present there; the HypothesisBacklogCard is what surfaces hypotheses on `/`.
 */

test('full workflow loop: Command Center -> Sectors -> hypothesis -> Terminal -> backlog', async ({ page }) => {
  // 1. Visit Command Center (the operational home; landing is at /welcome)
  await page.goto('/');
  await expect(page.locator('h1')).toContainText('Command Center');
  await expect(page.getByText('Today\'s Regime')).toBeVisible();

  // 2. Save a hypothesis from the Sectors page
  await page.goto('/sectors');
  // The SaveHypothesisPopover renders a "+" button carrying title="Save as hypothesis"
  await page.locator('button[title="Save as hypothesis"]').first().click();
  await page.getByPlaceholder('Why is this interesting?').fill('Tech leading with low vol');
  await page.locator('button:has-text("Save")').click();
  // Wait for the POST to land before leaving the page
  await expect(page.getByPlaceholder('Why is this interesting?')).toBeHidden();

  // 3. Visit the hypotheses page; confirm the row rendered with our `why` text
  await page.goto('/hypotheses');
  await expect(page.getByText('Tech leading with low vol')).toBeVisible();

  // 4. Visit the Terminal; the banner surfaces open hypotheses
  await page.goto('/terminal');
  await expect(page.getByText('open hypothesis')).toBeVisible();

  // 5. Command Center shows the hypothesis in the backlog card
  await page.goto('/');
  await expect(page.getByText('Tech leading with low vol')).toBeVisible();
});

test('deploying a strategy surfaces the Coach DEPLOYED badge in Strategy Lab', async ({ page, request }) => {
  // Seed a deployment via the real strategy-lab deploy endpoint. The strategy
  // file must be an existing, valid Strategy subclass (daily_golden_cross.py is
  // the canonical one). Deploying marks the strategy as the active deployment,
  // which the Strategy Lab library reads to show "Active" and which the Coach
  // summary uses to render the "DEPLOYED" badge.
  const deployRes = await request.post('/api/strategy-lab/sessions/_/deploy', {
    data: {
      strategy_class_path: 'backend/app/services/strategies/daily_golden_cross.py',
      // experiment_id is optional; omit it to seed without an experiment
      source_hypothesis_ids: [],
    },
  });
  expect(deployRes.ok()).toBeTruthy();

  await page.goto('/strategy-lab');

  // The library Status column reads "Active" for the deployed strategy
  await expect(page.getByText('Active', { exact: true })).toBeVisible();

  // The per-strategy Coach badge shows the DEPLOYED capsule
  await expect(page.getByText('DEPLOYED', { exact: true })).toBeVisible();
});
