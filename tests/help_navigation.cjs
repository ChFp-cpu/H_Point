async function openHelpTab(page, tab) {
  const button = page.locator('.helpNavigation [data-tab="' + tab + '"]');
  if (!(await button.isVisible())) await page.locator('#helpMore summary').click();
  await button.click();
}
module.exports = {openHelpTab};
