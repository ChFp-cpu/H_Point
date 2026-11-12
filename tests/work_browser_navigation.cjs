/* Operate the responsive work navigation as a user would. */
const aliases={'Обзор':'overview','Расписание':'bookings','Объекты':'objects','Задачи':'tasks','Сметы':'estimates','Услуги':'services','Клиенты':'clients','Команда':'team','Страница':'public','Страница организации':'public','Подписка':'subscription','Настройки':'profile','Отчёты':'performance'};
async function workTab(page,section){
 const nav=page.locator('.commercialNavigation');await nav.waitFor();
 const toggle=nav.locator('.commercialNavToggle');
 if(await toggle.isVisible()&&await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();
 const key=aliases[section]||section,button=nav.locator('[data-tab="'+key+'"]');
 await button.waitFor({state:'attached'});
 const group=button.locator('xpath=ancestor::details[1]');
 if(await group.count()&&!await group.evaluate(node=>node.open))await group.locator('summary').first().click();
 await button.click();
}
async function openEditor(page,key){const editor=page.locator('[data-editor-key="'+key+'"]');if(await editor.count()&&!await editor.evaluate(node=>node.open))await editor.locator('summary').first().click()}
module.exports={workTab,openEditor};
