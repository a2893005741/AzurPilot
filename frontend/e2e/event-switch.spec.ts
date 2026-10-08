import { expect, test, type Page } from '@playwright/test'

// 统一活动开关带动各活动任务，关卡名既能从当前活动的地图中下拉选择，也能手动填写。

async function pick(page: Page, trigger: string, option: string) {
  await page.locator(trigger).click()
  await page.getByRole('option', {name: option, exact: true}).click()
}

/* 切走再切回，让任务页重新向服务端取快照，确认已经真正保存。 */
async function reread(page: Page, task: string) {
  await page.evaluate(() => { location.hash = '#/i/testpilot/overview' })
  await page.evaluate(target => { location.hash = `#/i/testpilot/task/${target}` }, task)
}

test('统一活动切换全部活动任务，关卡可下拉选择或手动填写', async ({page}) => {
  await page.goto('/#/i/testpilot/task/EventGeneral')
  await pick(page, '[id="EventGeneral.EventGeneral.UnifiedEvent"]', '樊笼内的神光')
  await expect(page.locator('[id="EventGeneral.EventGeneral.UnifiedEvent"]')).toContainText('樊笼内的神光')

  for (const task of ['EventB', 'Event']) {
    await expect.poll(async () => {
      await reread(page, task)
      return page.locator(`[id="${task}.Campaign.Event"]`).textContent()
    }).toContain('樊笼内的神光')
  }

  const name = page.locator('[id="Event.Campaign.Name"]')
  const picker = page.getByRole('combobox', {name: /选择关卡/})
  await picker.click()
  await expect(page.getByRole('option', {name: 'SP', exact: true})).toBeVisible()
  await page.screenshot({path: 'test-results/event-switch-stage-menu.png'})
  await page.getByRole('option', {name: 'B2', exact: true}).click()
  await expect(name).toHaveValue('B2')
  await expect.poll(async () => {
    await reread(page, 'Event')
    return page.locator('[id="Event.Campaign.Name"]').inputValue()
  }).toBe('B2')

  await page.locator('[id="Event.Campaign.Name"]').fill('D3_3')
  await page.locator('[id="Event.Campaign.Name"]').blur()
  await expect.poll(async () => {
    await reread(page, 'Event')
    return page.locator('[id="Event.Campaign.Name"]').inputValue()
  }).toBe('D3_3')
  await expect(page.getByRole('combobox', {name: /选择关卡/})).toContainText('选择关卡')

  // 单独改一个任务的活动后，统一开关回到各任务分别选择。
  await pick(page, '[id="Event.Campaign.Event"]', '高塔上的蔷薇')
  await expect.poll(async () => {
    await reread(page, 'EventGeneral')
    return page.locator('[id="EventGeneral.EventGeneral.UnifiedEvent"]').textContent()
  }).toContain('各任务分别选择')

  await page.setViewportSize({width: 390, height: 844})
  await reread(page, 'Event')
  const row = page.locator('[id="Event.Campaign.Name"]').locator('xpath=ancestor::div[contains(@class,"field-row")]')
  await row.scrollIntoViewIfNeeded()
  await row.screenshot({path: 'test-results/event-switch-stage-mobile.png'})
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
