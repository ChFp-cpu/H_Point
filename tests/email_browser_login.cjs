/* Synthetic email identities prepared only by run_theme_qa.py. */
const assert=require('node:assert/strict');
const ids={'theme-browser-data':901,'theme-browser-empty':905,'theme-browser-game-deep':905,'mobile-helper':904};
async function emailLogin(page,ticket){
 const base=process.env.HPOINT_QA_URL;
 if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
 const id=ids[ticket];if(!id)throw Error('Unknown synthetic email identity');
 const result=await page.context().request.post(base+'/api/auth/login',{data:{email:'qa'+id+'@example.test',password:'SyntheticQa1'}});
 assert.equal(result.status(),200,await result.text());
 await page.goto(base+'/');await page.locator('#hpointWorkspace').waitFor();
 // Historical seed reviews are outside the workflow currently under test.
 await page.evaluate(()=>{const data=window.hpointWorkspace?.state?.data;for(const row of data?.requests||[])if(row.status==='done')localStorage.setItem('hp-review-shown:'+data.current_user_id+':'+row.id,'1')});
 return page;
}
module.exports={emailLogin};
