import {chromium, expect} from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
const root=path.resolve(".."), base="http://127.0.0.1:8000", out=path.join(root,"data/qa-marketplace");
await fs.mkdir(out,{recursive:true});
const credentials=process.env.TRACY_QA_OWNER === "1"
 ? JSON.parse(await fs.readFile(path.join(root,"data/tracy-owner.json"),"utf8"))
 : {email: "market-qa-"+crypto.randomUUID()+"@example.test",password:crypto.randomUUID()+"-qa-password"};
const offers=JSON.parse(await fs.readFile(path.join(root,"data/marketplace-demo.json"),"utf8"));
const recipient=JSON.parse(await fs.readFile(path.join(root,"data/presentation-recipient.json"),"utf8")).public_key;
const browser=await chromium.launch({channel:"chrome",headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
let page=await context.newPage();
const errors=[], report={checks:[],instances:[],started_at:new Date().toISOString()};
const listen=p=>p.on("pageerror",e=>errors.push(e.message)); listen(page);
const check=name=>{report.checks.push(name);console.log(name)};
let csrf="";
async function get(p){const r=await context.request.get(base+"/v1"+p);expect(r.ok()).toBeTruthy();return r.json()}
async function mutation(p,body){const r=await context.request.post(base+"/v1"+p,{headers:{"X-CSRF-Token":csrf},data:body});expect(r.ok()).toBeTruthy();return r.json()}
async function waitRun(id,status){await expect.poll(async()=>{
 const r=await get("/installations/"+id+"/runs"); return r.items[0]?.status;
},{timeout:120000,intervals:[1500,3000,5000]}).toBe(status)}
try{
 if(process.env.TRACY_QA_OWNER !== "1"){
   const created=await context.request.post(base+"/v1/auth/signup",{data:{...credentials,name:"Marketplace QA"}});
   expect(created.status()).toBe(201); await context.clearCookies();
 }
 await page.goto(base+"/a/"+offers.batch_payout);
 await page.getByRole("link",{name:"Use agent",exact:true}).click();
 await page.getByLabel("Email",{exact:true}).fill(credentials.email);
 await page.getByLabel("Password",{exact:true}).fill(credentials.password);
 await page.getByRole("button",{name:"Sign in",exact:true}).click();
 await expect(page.getByRole("heading",{name:"Make this agent yours"})).toBeVisible();
 check("Guest selection survives login and opens installation form");
 csrf=(await get("/auth/me")).csrf_token;
 await page.getByLabel("Your instance name",{exact:true}).fill("Atlas - my Devnet payouts");
 await page.getByLabel("Recipient 1",{exact:true}).fill(recipient);
 await page.getByLabel("Daily budget (SOL, UTC)",{exact:true}).fill("0.0000015");
 await page.getByRole("checkbox").check();
 await page.screenshot({path:path.join(out,"install-desktop.png"),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:path.join(out,"install-mobile.png"),fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 const installResponse=page.waitForResponse(r=>r.url()===base+"/v1/installations"&&r.request().method()==="POST");
 await page.getByRole("button",{name:"Install agent",exact:true}).click();
 const installed=await(await installResponse).json(); report.instances.push(installed.agent_id);
 await expect(page.getByRole("heading",{name:"Atlas - my Devnet payouts",exact:true})).toBeVisible();
 expect((await get("/installations/"+installed.agent_id+"/runs")).total).toBe(0);
 check("Private instance installed without sending funds");
 await page.getByRole("button",{name:"Run once",exact:true}).click();
 await waitRun(installed.agent_id,"COMPLETED");
 await page.reload();
 await expect(page.getByRole("link",{name:"Inspect proof",exact:false})).toHaveCount(1);
 const first=(await get("/installations/"+installed.agent_id+"/runs")).items[0];
 const receipt=first.actions[0].receipt_id;
 await expect.poll(async()=>{const r=await get("/receipts/"+receipt+"/verify");return r.valid},
   {timeout:90000,intervals:[3000,5000]}).toBe(true);
 report.verified_receipt=receipt;
 check("Real Devnet transfer completed; receipt independently verified after reload");
 await page.getByRole("button",{name:"Run once",exact:true}).click();
 await waitRun(installed.agent_id,"BLOCKED");
 const rejected=(await get("/installations/"+installed.agent_id+"/runs")).items[0];
 expect(rejected.reason).toBe("daily_budget_exceeded");
 expect(rejected.actions[0].status).toBe("REJECTED");
 check("Second transfer rejected by the customer's daily budget");
 await page.reload();
 await page.getByRole("button",{name:"Stop agent",exact:true}).click();
 await expect(page.getByRole("button",{name:"Resume agent",exact:true})).toBeVisible();
 await page.reload();
 await expect(page.getByRole("button",{name:"Run once",exact:true})).toBeDisabled();
 await page.locator("summary").filter({hasText:"Edit payout instructions"}).click();
 await page.getByLabel("Amount 1 (SOL)",{exact:true}).fill("0.0000005");
 await page.getByRole("button",{name:"Save payout plan",exact:true}).click();
 await expect(page.getByText("Payout instructions saved.",{exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Resume agent",exact:true}).click();
 check("Stop survives reload; plan edit and explicit resume work");
 // Leave a useful demo budget rather than the intentionally exhausted QA limit.
 const agent=(await get("/installations/"+installed.agent_id)).agent;
 const policyResponse=await context.request.put(base+"/v1/agents/"+installed.agent_id+"/policy",
  {headers:{"X-CSRF-Token":csrf},data:{expected_version:agent.policy_version,
    policy:{...agent.policy,daily_budget_sol:0.003}}});
 expect(policyResponse.ok()).toBeTruthy();
 await page.goto(base+"/a/"+offers.scheduled_payout);
 await page.getByRole("link",{name:"Use agent",exact:true}).click();
 await page.getByLabel("Your instance name",{exact:true}).fill("Sentinel - my scheduled payouts");
 await page.getByLabel("Recipient 1",{exact:true}).fill(recipient);
 await page.getByLabel("Interval (minutes)",{exact:true}).fill("1");
 await page.getByLabel("Number of cycles",{exact:true}).fill("2");
 await page.getByRole("checkbox").check();
 const scheduleResponse=page.waitForResponse(r=>r.url()===base+"/v1/installations"&&r.request().method()==="POST");
 await page.getByRole("button",{name:"Install agent",exact:true}).click();
 const scheduled=await(await scheduleResponse).json(); report.instances.push(scheduled.agent_id);
 await expect(page.getByRole("heading",{name:"Sentinel - my scheduled payouts",exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Start schedule",exact:true}).click();
 await page.close();
 await expect.poll(async()=>{
  const r=await get("/installations/"+scheduled.agent_id+"/runs");
  return r.items.filter(x=>x.status==="COMPLETED").length;
 },{timeout:160000,intervals:[3000,5000]}).toBe(2);
 expect((await get("/installations/"+scheduled.agent_id)).running).toBe(false);
 check("Two real scheduled cycles ran with the tab closed and stopped at the configured limit");
 page=await context.newPage();listen(page);
 await page.goto(base+"/installed/"+scheduled.agent_id);
 await expect(page.getByRole("link",{name:"Inspect proof",exact:false})).toHaveCount(2);
 await page.screenshot({path:path.join(out,"runs-desktop.png"),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:path.join(out,"runs-mobile.png"),fullPage:true});
 await page.goto(base+"/explore");
 await expect(page.getByRole("link",{name:"Use agent",exact:true})).toHaveCount(2);
 await page.screenshot({path:path.join(out,"catalog-mobile.png"),fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 await page.screenshot({path:path.join(out,"catalog-desktop.png"),fullPage:true});
 check("Desktop/mobile installation, history and catalog render without overflow");
 expect(errors).toEqual([]);
 report.passed=true;
}catch(e){
 report.passed=false;report.error=String(e);
 if(!page.isClosed())await page.screenshot({path:path.join(out,"failure.png"),fullPage:true});
 throw e;
}finally{
 // A failed browser test must never leave a recurring schedule running.
 for(const id of report.instances){try{const i=await get("/installations/"+id);
   if(i.running)await mutation("/installations/"+id+"/stop",{});}catch{}}
 report.browser_errors=errors;
 await fs.writeFile(path.join(out,"report.json"),JSON.stringify(report,null,2));
 await browser.close();
}
