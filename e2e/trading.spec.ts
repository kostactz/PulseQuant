import { test, expect } from '@playwright/test';

test.describe('E2E Trading Flow', () => {
  test.setTimeout(60000); // Allow 60s since WASM init takes time

  test('Engine reacts to massive deviation and executes trade', async ({ page }) => {
    // Open dashboard in PAPER mode with MockAdapter
    await page.goto('/?mock=true');
    
    // Welcome guide appears first visit
    const welcomeBanner = page.locator('text=Welcome to PulseQuant');
    await expect(welcomeBanner).toBeVisible({ timeout: 10000 });
    await page.click('button:has-text("Got it!")');
    await expect(welcomeBanner).toBeHidden();

    // Verify paper mode
    await expect(page.locator('button:has-text("Paper")')).toBeVisible();

    // Enable auto-trade
    const autoTradeButton = page.locator('button', { hasText: /Auto-Trad/ }).first();
    // Ensure it's not disabled (engine ready)
    await expect(autoTradeButton).not.toBeDisabled({ timeout: 25000 });
    
    const textContext = await autoTradeButton.textContent();
    if (!textContext?.includes('ON')) {
      await autoTradeButton.click();
    }
    
    // Wait for the engine to initialize and chart to render
    await expect(page.locator('text=Stat Arb Spread')).toBeVisible({ timeout: 10000 });

    // Inject massive deviation into window context
    await page.evaluate(() => {
      (window as any).__TRIGGER_MASSIVE_DEVIATION__ = true;
    });

    // Wait for trade to be executed and appear in TradesList
    const tradeEntry = page.locator('text=Fill').first();
    await expect(tradeEntry).toBeVisible({ timeout: 20000 });

    // Ensure positions or PnL updated
    const targetPosition = page.locator('text=Net PnL');
    await expect(targetPosition).toBeVisible();
  });
});
