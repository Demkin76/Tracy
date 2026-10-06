import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "./edge.mjs";
const env = { DAYTONA_ORIGIN: "https://8000-test-sandbox.proxy.daytona.work", DAYTONA_PREVIEW_TOKEN: "private-test-token" };
test("HTTP redirects to HTTPS and unknown hosts are rejected", async () => {
  const r = await worker.fetch(new Request("http://tracys.online/agents?tab=x"), env);
  assert.equal(r.status, 308);
  assert.equal(r.headers.get("location"), "https://tracys.online/agents?tab=x");
  assert.equal((await worker.fetch(new Request("https://other.example/"), env)).status, 421);
});
test("missing credentials and arbitrary origins fail closed", async () => {
  for (const changed of [{DAYTONA_PREVIEW_TOKEN:""}, {DAYTONA_ORIGIN:"https://evil.example"}, {DAYTONA_ORIGIN:"https://2280-test.proxy.daytona.work"}, {DAYTONA_ORIGIN:"http://8000-test.proxy.daytona.work"}]) {
    assert.equal((await worker.fetch(new Request("https://tracys.online/"), {...env,...changed})).status, 503);
  }
});
test("proxy pins the app port, replaces spoofed headers, preserves sessions and never follows redirects", async t => {
  const requests=[];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({url: String(url), options});
    return new Response(null, {status:302,headers:{location:env.DAYTONA_ORIGIN+"/login", "set-cookie":"tracy_session=test; Secure; HttpOnly", "x-daytona-preview-token":"must-not-leak"}});
  });
  const result=await worker.fetch(new Request("https://tracys.online//evil.example/v1?q=1", {headers:{"X-Daytona-Preview-Token":"attacker", "X-Forwarded-Host":"evil.example", "cookie":"tracy_session=test"}}),env);
  assert.equal(requests[0].url, env.DAYTONA_ORIGIN+"//evil.example/v1?q=1");
  assert.equal(requests[0].options.redirect,"manual");
  assert.equal(requests[0].options.headers.get("x-daytona-preview-token"),env.DAYTONA_PREVIEW_TOKEN);
  assert.equal(requests[0].options.headers.get("x-forwarded-host"),"tracys.online");
  assert.equal(requests[0].options.headers.get("cookie"),"tracy_session=test");
  assert.equal(result.headers.get("location"),"https://tracys.online/login");
  assert.equal(result.headers.get("x-daytona-preview-token"),null);
  assert.equal(result.headers.get("set-cookie"),"tracy_session=test; Secure; HttpOnly");
  assert.equal(result.headers.get("cache-control"),"no-store");
});
test("upstream failures return no internal diagnostics", async t => {
  t.mock.method(globalThis,"fetch",async()=>{throw new Error(env.DAYTONA_PREVIEW_TOKEN)});
  const result=await worker.fetch(new Request("https://tracys.online/"),env);
  assert.equal(result.status,503);
  assert.ok(!(await result.text()).includes(env.DAYTONA_PREVIEW_TOKEN));
});
test("accepts the EU preview hostname returned by Daytona while rejecting other hosts and ports", async t => {
  const calls=[];
  t.mock.method(globalThis,"fetch",async url => { calls.push(String(url)); return new Response("ready"); });
  const origin="https://8000-f89cd01c-92b9-43a6-9f70-1685cd9bc768.daytonaproxy01.eu";
  const r=await worker.fetch(new Request("https://tracys.online/readyz"), {...env,DAYTONA_ORIGIN:origin});
  assert.equal(r.status,200);
  assert.equal(calls[0],origin+"/readyz");
  for (const invalid of [origin.replace("8000-","2280-"),origin+".evil.example",origin.replace("daytonaproxy01.eu","evil.eu")]) {
    assert.equal((await worker.fetch(new Request("https://tracys.online/"),{...env,DAYTONA_ORIGIN:invalid})).status,503);
  }
  assert.equal(calls.length,1);
});
test("split routing keeps pages in Daytona and sends only API to the authenticated backend", async t => {
  const routed={...env,API_ORIGIN:"https://api-origin.tracys.online",API_ORIGIN_TOKEN:"a".repeat(40)};
  const calls=[];
  t.mock.method(globalThis,"fetch",async (url,options)=>{calls.push({url:String(url),headers:options.headers});return new Response("ok");});
  await worker.fetch(new Request("https://tracys.online/v1/auth/me",{headers:{"x-tracy-origin-token":"spoof","x-daytona-preview-token":"spoof"}}),routed);
  assert.equal(calls[0].url,routed.API_ORIGIN+"/v1/auth/me");
  assert.equal(calls[0].headers.get("x-tracy-origin-token"),routed.API_ORIGIN_TOKEN);
  assert.equal(calls[0].headers.get("x-daytona-preview-token"),null);
  await worker.fetch(new Request("https://tracys.online/lab",{headers:{"x-tracy-origin-token":"spoof"}}),routed);
  assert.equal(calls[1].url,env.DAYTONA_ORIGIN+"/lab");
  assert.equal(calls[1].headers.get("x-tracy-origin-token"),null);
  assert.equal((await worker.fetch(new Request("https://tracys.online/v1/auth/me"),{...routed,API_ORIGIN:"https://evil.example"})).status,503);
  assert.equal((await worker.fetch(new Request("https://tracys.online/v1/auth/me"),{...routed,API_ORIGIN_TOKEN:""})).status,503);
});
test("migration stops all API access while keeping the frontend available", async t => {
  t.mock.method(globalThis,"fetch",async()=>new Response("frontend"));
  for(const path of ["/v1/auth/login","/v1/adaptive/agents","/readyz"]){
    assert.equal((await worker.fetch(new Request("https://tracys.online"+path),{...env,API_MAINTENANCE:"true"})).status,503);
  }
  assert.equal((await worker.fetch(new Request("https://tracys.online/lab"),{...env,API_MAINTENANCE:"true"})).status,200);
});
test("AWS routes the whole site to one protected origin without Daytona credentials", async t => {
  const aws={AWS_ORIGIN:"https://aws-origin.tracys.online",AWS_ORIGIN_TOKEN:"a".repeat(40)};
  const calls=[];
  t.mock.method(globalThis,"fetch",async(url,opts)=>{calls.push({url:String(url),headers:opts.headers});return new Response("ok");});
  for (const path of ["/lab","/assets/main.js","/v1/auth/me","/readyz"]) {
    assert.equal((await worker.fetch(new Request("https://tracys.online"+path),aws)).status,200);
    assert.equal(calls.at(-1).url,aws.AWS_ORIGIN+path);
    assert.equal(calls.at(-1).headers.get("x-tracy-origin-token"),aws.AWS_ORIGIN_TOKEN);
    assert.equal(calls.at(-1).headers.get("x-daytona-preview-token"),null);
  }
  assert.equal((await worker.fetch(new Request("https://tracys.online/"),{...aws,AWS_ORIGIN:"https://evil.example"})).status,503);
});
