import { test, expect } from '@playwright/test';

test('homepage loads successfully', async ({ page }) => {
  await page.goto('/');

  // wait for the UI to be visible
  await expect(page.locator('body')).toBeVisible();
});