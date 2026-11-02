async function openHelpTab(page, tab) {
  if(tab==='preferences'){await openHelpTab(page,'open');await page.locator('[data-ws-action="help-tab"][data-tab="preferences"]').first().click();return}
  const button = page.locator('.helpNavigation [data-tab="' + tab + '"]');
  if (!(await button.isVisible())) await page.locator('#helpMore summary').click();
  await button.click();
}
module.exports = {openHelpTab};
