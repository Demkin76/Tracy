import {chromium,expect} from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
const root=path.resolve(".."),out=path.join(root,"data/week3-video"),base="http://127.0.0.1:8000";
const credentials=JSON.parse(await fs.readFile(path.join(root,"data/tracy-owner.json"),"utf8"));
const demos=JSON.parse(await fs.readFile(path.join(root,"data/trading-demo.json"),"utf8"));
const browser=await chromium.launch({channel:"chrome",headless:true});
const login=await browser.newContext();
const response=await login.request.post(base+"/v1/auth/login",{data:{email:credentials.email,password:credentials.password}});
expect(response.ok()).toBeTruthy();
const state=await login.storageState();await login.close();
const context=await browser.newContext({storageState:state,viewport:{width:1600,height:900},deviceScaleFactor:1,recordVideo:{dir:path.join(out,"raw"),size:{width:1600,height:900}}});
await context.addInitScript(()=>{
 document.addEventListener("DOMContentLoaded",()=>{
  const cursor=document.createElement("div");cursor.id="demo-cursor";
  cursor.innerHTML='<svg width="24" height="30" viewBox="0 0 24 30"><path d="M3 2 L3 24 L9 18 L14 28 L18 26 L13 16 L22 16 Z" fill="white" stroke="black" stroke-width="1.5"/></svg>';
  cursor.style.cssText="position:fixed;left:1500px;top:850px;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 1px 2px #0004)";
  document.body.append(cursor);
  document.addEventListener("mousemove",e=>{cursor.style.left=e.clientX+"px";cursor.style.top=e.clientY+"px"});
 });
});
const page=await context.newPage(),events=[],errors=[];page.on("pageerror",e=>errors.push(e.message));
const sid=demos[0].strategy_id,url=base+"/strategies/"+sid;
let start;
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function at(t,label,action){await wait(Math.max(0,t*1000-(performance.now()-start)));events.push({time:(performance.now()-start)/1000,label});console.log(label);await action();}
async function click(locator){await locator.scrollIntoViewIfNeeded();const b=await locator.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2,{steps:15});await wait(180);await locator.click();}
async function scroll(y){await page.evaluate(y=>window.scrollTo({top:y,behavior:"smooth"}),y);await wait(650);}
try{
 await page.goto(base);await expect(page.getByRole("heading",{name:"Is your strategy still working?"})).toBeVisible();await wait(1500);
 start=performance.now();
 await at(0,"Overview",async()=>{await page.mouse.move(1530,850);});
 await at(19.9,"Open SOL Momentum",async()=>{await page.goto(url);await expect(page.getByRole("button",{name:"Tests",exact:true})).toBeVisible();});
 await at(22,"Version and test results",async()=>{await click(page.getByRole("button",{name:"Tests",exact:true}));await scroll(150);});
 await at(30,"Pinned backtest",async()=>{const b=await page.getByRole("heading",{name:"Reproducible test runs"}).boundingBox();await page.mouse.move(b.x+140,b.y+90,{steps:20});});
 await at(35,"Performance gap",async()=>{await click(page.getByRole("button",{name:"Performance",exact:true}));await scroll(180);});
 await at(41,"Backtest versus paper live",async()=>{await page.mouse.move(970,295,{steps:20});});
 await at(47.6,"Health breakdown",async()=>{await click(page.getByText(/Why .*View formula/));await scroll(530);await page.mouse.move(1480,860,{steps:20});});
 await at(59.1,"Trade evidence",async()=>{await click(page.getByRole("button",{name:"Trades & proofs",exact:true}));await scroll(310);});
 await at(60.4,"Open Trading Proof",async()=>{await click(page.getByRole("link",{name:"Open proof",exact:false}).first());await expect(page.getByRole("heading",{name:"Trading Proof",exact:true})).toBeVisible();await scroll(70);});
 await at(63.1,"Verify signatures and readback",async()=>{await click(page.getByRole("button",{name:"Verify proof now",exact:true}));await expect(page.locator("pre").filter({hasText:'"browser_hash_signature_chain": true'})).toBeVisible();await scroll(280);});
 await at(67.35,"Trading guardrails",async()=>{await page.goto(url);await click(page.getByRole("button",{name:"Guardrails",exact:true}));await page.getByRole("button",{name:"Submit oversized demo order"}).scrollIntoViewIfNeeded();});
 await at(71,"Reject oversized demo order",async()=>{await click(page.getByRole("button",{name:"Submit oversized demo order"}));await expect(page.getByRole("heading",{name:"Trading intent & decision"})).toBeVisible();await expect(page.getByText("max trade size",{exact:true})).toBeVisible();await scroll(0);});
 await at(76.7,"Public exchange",async()=>{await page.goto(base+"/explore");await expect(page.getByRole("heading",{name:"Performance. Risk. Evidence."})).toBeVisible();});
 await at(80,"Compare published strategies",async()=>{await page.goto(base+"/compare?ids="+demos.map(d=>d.strategy_id).join(","));await expect(page.getByRole("rowheader",{name:"Backtest/live gap",exact:true})).toBeVisible();await scroll(200);await page.mouse.move(1500,850,{steps:20});});
 await at(87,"Evidence mode and risk comparison",async()=>{await scroll(380);});
 await at(94.3,"Closing comparison",async()=>{await scroll(150);});
 await at(97.432,"End",async()=>{});
 await expect(page.getByRole("rowheader",{name:"Evidence mode",exact:true})).toBeVisible();expect(errors).toEqual([]);
}finally{
 const video=page.video();await context.close();
 const file=await video.path();await fs.writeFile(path.join(out,"recording.json"),JSON.stringify({file,events,errors,duration:97.432},null,2));
 await browser.close();
}
