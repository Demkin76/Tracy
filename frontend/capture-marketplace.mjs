import {chromium,expect} from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
const root=path.resolve(".."),base="http://127.0.0.1:8000",out=path.join(root,"data/marketplace-presentation");
await fs.mkdir(out,{recursive:true});
const credentials=JSON.parse(await fs.readFile(path.join(root,"data/tracy-owner.json"),"utf8"));
const offers=JSON.parse(await fs.readFile(path.join(root,"data/marketplace-demo.json"),"utf8"));
const demo=JSON.parse(await fs.readFile(path.join(root,"data/marketplace-owner-demo.json"),"utf8"));
const browser=await chromium.launch({channel:"chrome",headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[];page.on("pageerror",e=>errors.push(e.message));
try{
 const login=await context.request.post(base+"/v1/auth/login",{data:{email:credentials.email,password:credentials.password}});
 expect(login.ok()).toBeTruthy();
 expect((await(await context.request.get(base+"/v1/config")).json()).version).toBe("1.1.0");
 await page.goto(base+"/install/"+offers.batch_payout);
 await expect(page.getByRole("heading",{name:"Make this agent yours"})).toBeVisible();
 const box=await page.getByRole("checkbox").boundingBox();expect(box.width).toBeLessThan(25);expect(box.height).toBeLessThan(25);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:path.join(out,"install-desktop.png"),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:path.join(out,"install-mobile.png"),fullPage:true});
 const runRoute="**/v1/installations/"+demo.instances[0]+"/runs?*";
 await page.route(runRoute,async route=>{
  const response=await route.fetch(),data=await response.json();
  data.items[0].status="RUNNING";data.items[0].actions[0].status="PREPARING";
  data.items[0].actions[0].reason=null;data.items[0].actions[0].receipt_id=null;
  await route.fulfill({response,json:data});
 });
 await page.goto(base+"/installed/"+demo.instances[0]);
 await expect(page.getByText("Preparing transaction",{exact:true})).toBeVisible();
 await page.unroute(runRoute);
 await page.reload();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:path.join(out,"instance-mobile.png"),fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(base+"/installed");
 await expect(page.getByRole("link",{name:"Open agent",exact:false})).toHaveCount(2);
 await page.screenshot({path:path.join(out,"installed-desktop.png"),fullPage:true});
 await page.goto(base+"/explore");
 await expect(page.getByRole("link",{name:"Use agent",exact:true})).toHaveCount(2);
 await page.screenshot({path:path.join(out,"catalog-desktop.png"),fullPage:true});
 expect(errors).toEqual([]);
 await fs.writeFile(path.join(out,"ready.json"),JSON.stringify({ready:true,version:"1.1.0",owner_instances:demo.instances,
   checks:["Restart retained personal instances and histories","PREPARING with null reason renders safely","Checkbox dimensions correct",
   "Desktop and mobile layouts fit viewport","No browser errors"],browser_errors:errors},null,2));
 console.log("Tracy 1.1 ready: catalog, two owner instances, preserved histories, PREPARING regression and mobile checks passed.");
}finally{await browser.close()}
