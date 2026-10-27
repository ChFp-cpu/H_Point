async function openHelpTab(page, tab) {
  if(tab==='preferences'){await page.getByRole('button',{name:'Настроить помощь',exact:true}).click();return}
  const button = page.locator('.helpNavigation [data-tab="' + tab + '"]');
  if (!(await button.isVisible())) await page.locator('#helpMore summary').click();
  await button.click();
}
module.exports = {openHelpTab};
