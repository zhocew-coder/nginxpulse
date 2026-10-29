import { test, expect } from '@playwright/test';

test.describe('AI Page', () => {
  test('should load AI page successfully', async ({ page }) => {
    // 访问 AI 页面
    await page.goto('http://localhost:8088/ai');
    
    // 等待页面加载
    await page.waitForLoadState('networkidle');
    
    // 检查页面标题
    await expect(page).toHaveTitle(/NginxPulse/);
    
    // 检查 AI 页面标题
    const aiTitle = page.locator('h1');
    await expect(aiTitle).toBeVisible();
    await expect(aiTitle).toContainText('AI 智能分析');
  });

  test('should display three main sections', async ({ page }) => {
    await page.goto('http://localhost:8088/ai');
    await page.waitForLoadState('networkidle');
    
    // 检查智能查询模块
    const querySection = page.locator('h2').filter({ hasText: '智能查询' });
    await expect(querySection).toBeVisible();
    
    // 检查异常检测模块
    const anomalySection = page.locator('h2').filter({ hasText: '异常流量检测' });
    await expect(anomalySection).toBeVisible();
    
    // 检查报表生成模块
    const reportSection = page.locator('h2').filter({ hasText: '智能报表' });
    await expect(reportSection).toBeVisible();
  });

  test('should test AI query functionality', async ({ page }) => {
    await page.goto('http://localhost:8088/ai');
    await page.waitForLoadState('networkidle');
    
    // 找到输入框并输入问题
    const queryInput = page.locator('input[placeholder*="今天有多少 PV"]');
    await expect(queryInput).toBeVisible();
    
    // 输入测试问题
    await queryInput.fill('今天有多少 PV？');
    
    // 点击查询按钮
    const queryButton = page.locator('button').filter({ hasText: '查询' });
    await queryButton.click();
    
    // 等待查询结果
    await page.waitForTimeout(5000);
    
    // 检查是否有结果展示
    const queryResult = page.locator('.query-result');
    await expect(queryResult).toBeVisible();
    
    // 检查答案显示
    const answer = page.locator('.query-answer');
    await expect(answer).toBeVisible();
  });

  test('should test anomaly detection', async ({ page }) => {
    await page.goto('http://localhost:8088/ai');
    await page.waitForLoadState('networkidle');
    
    // 找到异常检测按钮
    const detectButton = page.locator('button').filter({ hasText: '开始检测' });
    await expect(detectButton).toBeVisible();
    
    // 点击检测按钮
    await detectButton.click();
    
    // 等待检测结果
    await page.waitForTimeout(5000);
    
    // 检查是否有结果（可能有也可能没有异常）
    const anomalyResult = page.locator('.anomaly-result, .anomaly-empty');
    await expect(anomalyResult).toBeVisible();
  });

  test('should test report generation', async ({ page }) => {
    await page.goto('http://localhost:8088/ai');
    await page.waitForLoadState('networkidle');
    
    // 选择报表类型
    const reportTypeDropdown = page.locator('label').filter({ hasText: '报表类型' }).locator('..').locator('select');
    await expect(reportTypeDropdown).toBeVisible();
    
    // 选择日期
    const dateInput = page.locator('label').filter({ hasText: '日期' }).locator('..').locator('input');
    await expect(dateInput).toBeVisible();
    
    // 点击生成报表按钮
    const generateButton = page.locator('button').filter({ hasText: '生成报表' });
    await expect(generateButton).toBeVisible();
  });
});
