import { test, expect } from '@playwright/test';

test('homepage loads successfully', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).toBeVisible();
});

test('passwordless paper onboarding with live mode gating', async ({ page }) => {
  await page.goto('/');

  // Welcome guide appears first visit
  const welcomeBanner = page.locator('text=Welcome to PulseQuant');
  await expect(welcomeBanner).toBeVisible();

  await page.click('button:has-text("Got it!")');
  await expect(welcomeBanner).toBeHidden();

  // No security modal for paper mode
  await expect(page.locator('text=Setup Trading Credentials')).toBeHidden();

  // Lock button should not be shown in PAPER mode
  await expect(page.locator('button:has-text("Lock")')).toBeHidden();

  // Switch to testnet triggers credentials modal
  await page.click('button:has-text("Testnet")');
  await expect(page.locator('text=Setup Trading Credentials')).toBeVisible();

  // Lock button appears in TESTNET mode as soon as modal is shown/ready to lock
  await expect(page.locator('button:has-text("Lock")')).toBeVisible();

  // Skip for now returns to paper mode
  await page.click('text=Skip for now (return to Paper mode)');
  await expect(page.locator('text=Setup Trading Credentials')).toBeHidden();

  // Setup credentials to enable live mode and rotate button
  await page.click('button:has-text("Testnet")');
  await expect(page.locator('text=Setup Trading Credentials')).toBeVisible();

  await page.fill('input[placeholder="Create a strong password"]', 'testpass');
  await page.fill('input[placeholder="Enter API Key"]', 'dummy-key');
  await page.fill('input[placeholder="Enter Secret Key"]', 'dummy-secret');
  await page.click('button:has-text("Encrypt & Save")');

  // Wait for unlock after setup
  await expect(page.locator('text=Setup Trading Credentials')).toBeHidden();

  // Mode toggle to make sure route is live
  await page.click('button:has-text("Testnet")');

  // Rotate credentials appears in live mode with runtime creds
  const rotateBtn = page.locator('button:has-text("Rotate Credentials")');
  await expect(rotateBtn).toBeVisible();

  // Rotate resets to setup flow
  await rotateBtn.click();
  await expect(page.locator('text=Setup Trading Credentials')).toBeVisible();
});