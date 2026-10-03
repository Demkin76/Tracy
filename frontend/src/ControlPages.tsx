import React, {useEffect,useState} from "react";
import {Link,useNavigate,useParams} from "react-router-dom";
import canonicalize from "canonicalize";
import {Agent,api,base64,download} from "./api";
import {useApp} from "./app-context";
import {ErrorNotice,err,Status,when} from "./PublicPages";

type Resource={id:string;kind:string;label:string;actions:string[];asset:string;configured:boolean;trust_boundary:string;unit_description:string};
type Rule={action:string;resource_id:string;allowed_targets:string[];max_units_per_action:number;daily_units:number;require_approval:boolean};
type Policy={rules:Rule[];max_per_minute:number;max_denials_per_hour:number;review_new_targets:boolean;approval_ttl_seconds:number};
type Task={task_id:string;agent_id:string;purpose:string;active:boolean;expires_at:number;body:{allowed_resources:string[];allowed_actions:string[]}};
type Intent={intent_id:string;agent_id:string;status:string;reason:string;action:string;resource_id:string;intent_hash:string;
 policy_version:number;created_at:number;approval_expires_at:number|null;target:string;units:number;asset:string;
 request:{params:Record<string,unknown>;reason:string};context:{task:{purpose:string}};policy:Policy;approval:unknown;
 receipt:null|{verification:Record<string,unknown>;receipt_hash:string;status:string}};
const emptyPolicy=():Policy=>({rules:[],max_per_minute:10,max_denials_per_hour:5,review_new_targets:true,approval_ttl_seconds:900});
const label=(s:string)=>s.replaceAll("_"," ");
function Json({value}:{value:unknown}){return <pre className="control-json">{JSON.stringify(value,null,2)}</pre>}

export function ControlHome({approvals=false}:{approvals?:boolean}){
 const {agents,refresh,setSession}=useApp(),navigate=useNavigate();
 const [items,setItems]=useState<Intent[]>([]),[total,setTotal]=useState(0),[page,setPage]=useState(0),
 [filter,setFilter]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false),[name,setName]=useState("");
 const [keyFile,setKeyFile]=useState<Record<string,string>|null>(null);
 async function load(){const r=await api<{items:Intent[];total:number}>("/v2/intents?limit=20&offset="+page*20+"&status="+(approvals?"AWAITING_APPROVAL":filter));setItems(r.items);setTotal(r.total)}
 useEffect(()=>{void load().catch(e=>setError(err(e)));const timer=setInterval(()=>void load().catch(e=>setError(err(e))),5000);return()=>clearInterval(timer)},[page,filter,approvals]);
 async function create(e:React.FormEvent){e.preventDefault();setBusy(true);setError("");try{
  const pair=await crypto.subtle.generateKey("Ed25519",true,["sign","verify"]) as CryptoKeyPair;
  const agent=await api<Agent>("/v2/agents",{method:"POST",body:JSON.stringify({agent_id:"agent_"+crypto.randomUUID().replaceAll("-",""),
    name,public_key:base64(await crypto.subtle.exportKey("raw",pair.publicKey))})});
  const jwk=await crypto.subtle.exportKey("jwk",pair.privateKey);
  const seed=jwk.d!.replaceAll("-","+").replaceAll("_","/");
  setKeyFile({agent_id:agent.agent_id,private_seed:seed+"=".repeat((4-seed.length%4)%4)});
  setSession({agent,key:pair.privateKey});await refresh();setName("");
 }catch(e){setError(err(e))}finally{setBusy(false)}}
 return <>
  <div className="page-heading"><div><div className="eyebrow">TRACY / CONTROL LAYER</div><h1>{approvals?"Human approvals":"Agent control center"}</h1>
  <p>What did the agent request? Was it allowed? What actually happened?</p></div><Link className="primary" to={approvals?"/control":"/control/approvals"}>{approvals?"All intents":"Review approvals"}</Link></div>
  <ErrorNotice error={error}/>
  {!approvals&&<><section className="panel editor control-intro"><h2>Put sensitive actions behind your rules</h2>
   <p>Register an agent, grant a scoped task, and set its policy. Tracy holds execution credentials, checks every signed intent,
    requests human approval when required, then reads the result back and signs a receipt.</p>
   <div className="button-row"><Link className="secondary" to="/control/resources">Execution resources</Link><Link className="secondary" to="/control/integrations">API, SDK & MCP</Link></div>
   <p className="muted">Protection covers credentials and tools routed through Tracy. Remove direct provider credentials from the agent process.
    Existing payouts and the public directory remain available as applications of this infrastructure.</p></section>
   <div className="settings-grid"><form className="panel editor" onSubmit={create}><h2>Create a protected agent</h2>
    <label>Protected agent name<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
    <button className="primary" disabled={busy}>Create protected agent</button>
    <p>New agents start with deny-all policies. This browser holds only the intent-signing key.</p>
    {keyFile&&<div className="notice">Save the identity file for SDK/MCP use. The browser key is lost on refresh.
      <div className="button-row"><button type="button" className="secondary" onClick={()=>download(keyFile,"tracy-agent.json")}>Download agent identity</button>
      <Link className="primary" to={"/control/agents/"+keyFile.agent_id}>Configure policy & task</Link></div></div>}
   </form><section className="panel editor"><h2>Manage an existing agent</h2>
    <label>Agent<select aria-label="Configure existing agent" defaultValue="" onChange={e=>{if(e.target.value)navigate("/control/agents/"+e.target.value)}}>
      <option value="">Choose an agent</option>{agents.map(a=><option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}</select></label>
    <p>Enabling a control policy disables this identity's legacy transfer endpoint. Existing sent transactions remain in its history.</p>
    <Link to="/agents">View agent identities</Link></section></div></>}
  <section className="panel editor"><div className="toolbar"><h2>{approvals?"Waiting for your decision":"Intent history"}</h2>
  {!approvals&&<select aria-label="Intent status" value={filter} onChange={e=>{setFilter(e.target.value);setPage(0)}}>
    <option value="">All statuses</option>{["AWAITING_APPROVAL","QUEUED","DISPATCHED","UNCERTAIN","VERIFIED","REJECTED","FAILED"].map(s=><option key={s}>{s}</option>)}</select>}</div>
  {!items.length&&<p>{approvals?"No approvals waiting.":"No intents yet. Configure an agent and submit a request through SDK, MCP or the test form."}</p>}
  {items.map(i=><article className="run-card" key={i.intent_id}><div className="toolbar"><Link to={"/control/intents/"+i.intent_id}><strong>{i.action}</strong></Link><Status value={i.status}/></div>
   <p>{i.resource_id} · {i.units} {i.asset} · {when(i.created_at)}</p><p>{label(i.reason)}</p>
   <Link to={"/control/intents/"+i.intent_id}>Inspect intent, decision & evidence →</Link></article>)}
  <div className="button-row"><button disabled={!page} onClick={()=>setPage(p=>p-1)}>Previous</button><span>{total} intents</span>
   <button disabled={(page+1)*20>=total} onClick={()=>setPage(p=>p+1)}>Next</button></div></section>
 </>;
}

export function ControlAgent(){
 const {id}=useParams(),{agents,session,refresh}=useApp();
 const agent=agents.find(a=>a.agent_id===id);
 const [resources,setResources]=useState<Resource[]>([]),[policy,setPolicy]=useState<Policy>(emptyPolicy),[version,setVersion]=useState(0),
 [tasks,setTasks]=useState<Task[]>([]),[purpose,setPurpose]=useState(""),[ttl,setTtl]=useState(3600),
 [error,setError]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false),
 [taskId,setTaskId]=useState(""),[resourceId,setResourceId]=useState(""),[action,setAction]=useState(""),[params,setParams]=useState('{"record":{"message":"Hello Tracy"}}');
 const navigate=useNavigate();
 async function load(){const [r,p,t]=await Promise.all([api<{items:Resource[]}>("/v2/resources"),
  api<{version:number;policy:Policy|null}>("/v2/agents/"+id+"/policy"),api<{items:Task[]}>("/v2/tasks?agent_id="+id)]);
  setResources(r.items);setPolicy(p.policy||emptyPolicy());setVersion(p.version);setTasks(t.items)}
 useEffect(()=>{void load().catch(e=>setError(err(e)))},[id]);
 async function perform(fn:()=>Promise<unknown>,text:string){setBusy(true);setError("");setNotice("");try{await fn();await load();await refresh();setNotice(text)}catch(e){setError(err(e))}finally{setBusy(false)}}
 function change(index:number,values:Partial<Rule>){setPolicy({...policy,rules:policy.rules.map((r,i)=>i===index?{...r,...values}:r)})}
 return <><Link className="breadcrumb" to="/control">← Control center</Link><h1>{agent?.name||"Agent policy"}</h1><ErrorNotice error={error}/>
  {notice&&<div className="notice" role="status">{notice}</div>}
  <div className="button-row"><button className="secondary" disabled={busy} onClick={()=>void perform(()=>api("/agents/"+id+"/status",{method:"POST",body:JSON.stringify({active:!agent?.active})}),agent?.active?"Agent stopped. Unsent intents will be denied.":"Agent resumed.")}>{agent?.active?"Stop agent":"Resume agent"}</button>
   <button className="secondary" onClick={()=>void api("/v2/agents/"+id+"/export").then(b=>download(b,"tracy-audit.json")).catch(e=>setError(err(e)))}>Export signed audit trail</button></div>
  <form className="panel editor control-section" onSubmit={e=>{e.preventDefault();void perform(()=>api("/v2/agents/"+id+"/policy",{method:"PUT",body:JSON.stringify({expected_version:version,policy})}),"Policy saved. Earlier approvals and queued intents using the old version are invalidated.")}}>
   <h2>Control policy · version {version}</h2><p>Only these exact actions, resources and targets are allowed. Every new identity starts with no permissions.</p>
   {policy.rules.map((r,i)=><fieldset className="control-rule" key={i}><legend>Permission {i+1}</legend>
    <label>Resource<select aria-label={"Rule resource "+(i+1)} value={r.resource_id} onChange={e=>{const x=resources.find(x=>x.id===e.target.value)!;change(i,{resource_id:x.id,action:x.actions[0],allowed_targets:[]})}}>
     {resources.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
    <label>Action<select aria-label={"Rule action "+(i+1)} value={r.action} onChange={e=>change(i,{action:e.target.value})}>
      {resources.find(x=>x.id===r.resource_id)?.actions.map(a=><option key={a}>{a}</option>)}</select></label>
    <p className="muted">{resources.find(x=>x.id===r.resource_id)?.unit_description}</p>
    <label>Allowed targets<textarea aria-label={"Allowed targets "+(i+1)} required value={r.allowed_targets.join("\n")}
      placeholder="One exact target per line: wallet address, owner/repo, tracy_records, or API operation name"
      onChange={e=>change(i,{allowed_targets:e.target.value.split("\n")})}/></label>
    <div className="payout-row"><label>Maximum units per action<input required type="number" min="1" step="1" value={r.max_units_per_action} onChange={e=>change(i,{max_units_per_action:Number(e.target.value)})}/></label>
      <label>Daily units (UTC)<input required type="number" min="1" step="1" value={r.daily_units} onChange={e=>change(i,{daily_units:Number(e.target.value)})}/></label></div>
    <label className="consent"><input type="checkbox" checked={r.require_approval} onChange={e=>change(i,{require_approval:e.target.checked})}/>Require human approval for every action</label>
    <button type="button" onClick={()=>setPolicy({...policy,rules:policy.rules.filter((_,n)=>n!==i)})}>Remove permission</button></fieldset>)}
   <button type="button" className="secondary" disabled={!resources.length} onClick={()=>setPolicy({...policy,rules:[...policy.rules,{action:resources[0].actions[0],resource_id:resources[0].id,allowed_targets:[],max_units_per_action:1,daily_units:10,require_approval:true}]})}>Add permission</button>
   <div className="payout-row"><label>Maximum requests per minute<input type="number" min="1" max="1000" value={policy.max_per_minute} onChange={e=>setPolicy({...policy,max_per_minute:Number(e.target.value)})}/></label>
    <label>Denial threshold per hour<input type="number" min="1" max="1000" value={policy.max_denials_per_hour} onChange={e=>setPolicy({...policy,max_denials_per_hour:Number(e.target.value)})}/></label>
    <label>Approval lifetime (seconds)<input type="number" min="30" max="86400" value={policy.approval_ttl_seconds} onChange={e=>setPolicy({...policy,approval_ttl_seconds:Number(e.target.value)})}/></label></div>
   <label className="consent"><input type="checkbox" checked={policy.review_new_targets} onChange={e=>setPolicy({...policy,review_new_targets:e.target.checked})}/>Require approval for a target with no verified history</label>
   <p className="muted">Anomaly checks are explicit rate, denial and new-target rules. They do not infer whether an agent's reasoning is trustworthy.</p>
   <button className="primary" disabled={busy}>Save control policy</button></form>
  <form className="panel editor control-section" onSubmit={e=>{e.preventDefault();void perform(()=>api("/v2/tasks",{method:"POST",body:JSON.stringify({agent_id:id,purpose,expires_in_seconds:ttl,
    allowed_resources:[...new Set(policy.rules.map(r=>r.resource_id))],allowed_actions:[...new Set(policy.rules.map(r=>r.action))]})}),"Task granted. Copy its ID into your agent configuration.")}}>
   <h2>Grant a task</h2><label>Task purpose<input required minLength={3} maxLength={1000} value={purpose} onChange={e=>setPurpose(e.target.value)}/></label>
   <label>Task lifetime (seconds)<input type="number" min="60" max="604800" value={ttl} onChange={e=>setTtl(Number(e.target.value))}/></label>
   <p>Scope: the actions and resources in the policy shown above. Save policy changes before granting a task.</p>
   <button className="primary" disabled={busy||!policy.rules.length}>Grant task</button>
   {tasks.map(t=><div className="run-card" key={t.task_id}><strong>{t.purpose}</strong><code className="break-word">{t.task_id}</code><p>{t.active?"Active":"Revoked"} · expires {when(t.expires_at)}</p>
     {t.active&&<button type="button" onClick={()=>void perform(()=>api("/v2/tasks/"+t.task_id+"/revoke",{method:"POST"}),"Task revoked.")}>Revoke task</button>}</div>)}</form>
  <details className="panel editor control-section"><summary>Submit a test intent</summary>
   <p>Uses this session's agent identity. The request follows the same policy, approval and execution path as SDK/MCP requests.</p>
   {session?.agent.agent_id!==id?<p>Create an agent in this browser session to test here, or use the SDK with its saved identity file.</p>:
    <form onSubmit={async e=>{e.preventDefault();setBusy(true);setError("");try{
      const body={schema_version:"tracy.intent/2",request_id:"req_"+crypto.randomUUID().replaceAll("-",""),agent_id:id,task_id:taskId,action,resource_id:resourceId,params:JSON.parse(params),reason:"Browser integration test",timestamp:Math.floor(Date.now()/1000)};
      const signature=base64(await crypto.subtle.sign("Ed25519",session!.key,new TextEncoder().encode(canonicalize(body)!)));
      const result=await api<Intent>("/v2/intents",{method:"POST",body:JSON.stringify({...body,signature})});navigate("/control/intents/"+result.intent_id);
    }catch(e){setError(err(e))}finally{setBusy(false)}}}>
    <label>Granted task<select required aria-label="Granted task" value={taskId} onChange={e=>setTaskId(e.target.value)}><option value="">Choose task</option>{tasks.filter(t=>t.active&&t.expires_at>Date.now()/1000).map(t=><option key={t.task_id} value={t.task_id}>{t.purpose}</option>)}</select></label>
    <label>Execution resource<select required aria-label="Execution resource" value={resourceId} onChange={e=>{setResourceId(e.target.value);setAction(resources.find(r=>r.id===e.target.value)!.actions[0])}}><option value="">Choose resource</option>{resources.map(r=><option value={r.id} key={r.id}>{r.label}</option>)}</select></label>
    <label>Action<input readOnly value={action}/></label><label>Intent parameters (JSON)<textarea required aria-label="Intent parameters" value={params} onChange={e=>setParams(e.target.value)}/></label>
    <button className="primary" disabled={busy}>Submit signed intent</button></form>}
  </details>
 </>;
}

export function IntentPage(){
 const {id}=useParams();const [item,setItem]=useState<Intent|null>(null),[error,setError]=useState(""),[note,setNote]=useState(""),
 [busy,setBusy]=useState(false),[checks,setChecks]=useState<Record<string,unknown>|null>(null);
 async function load(){setItem(await api<Intent>("/v2/intents/"+id))}
 useEffect(()=>{void load().catch(e=>setError(err(e)));const t=setInterval(()=>void load().catch(e=>setError(err(e))),3000);return()=>clearInterval(t)},[id]);
 async function decide(decision:string){if(!item)return;setBusy(true);setError("");try{await api("/v2/intents/"+id+"/decision",{method:"POST",body:JSON.stringify({decision,intent_hash:item.intent_hash,policy_version:item.policy_version,note})});await load()}catch(e){setError(err(e))}finally{setBusy(false)}}
 return <><Link className="breadcrumb" to="/control">← Control center</Link><h1>Intent, decision & evidence</h1><ErrorNotice error={error}/>
  {item&&<><div className="toolbar"><code className="break-word">{item.intent_id}</code><Status value={item.status}/></div>
   <section className="panel editor"><h2>1. What did the agent want?</h2><p><strong>{item.action}</strong> through {item.resource_id}</p>
    <p>Task: {item.context.task.purpose}</p><p>Agent explanation: {item.request.reason||"Not supplied"}</p><Json value={item.request.params}/></section>
   <section className="panel editor control-section"><h2>2. Was it allowed?</h2><p>Policy version {item.policy_version} · {label(item.reason)}</p>
    <p>Target: <code className="break-word">{item.target}</code> · {item.units} {item.asset}</p>
    <details><summary>Exact policy snapshot and context</summary><Json value={{policy:item.policy,context:item.context}}/></details>
    {item.status==="AWAITING_APPROVAL"&&<div className="approval-box"><h3>Human decision required</h3><p>Review the exact request above. Approval applies only to this intent and policy version.</p>
      <p>Expires: {when(item.approval_expires_at)}</p><label>Decision note<input value={note} maxLength={500} onChange={e=>setNote(e.target.value)}/></label>
      <div className="button-row"><button className="primary" disabled={busy} onClick={()=>void decide("approve")}>Approve this intent</button>
       <button className="secondary" disabled={busy} onClick={()=>void decide("deny")}>Deny this intent</button></div></div>}
    {item.approval!==null&&<details><summary>Recorded human decision</summary><Json value={item.approval}/></details>}</section>
   <section className="panel editor control-section"><h2>3. What actually happened?</h2>
    {item.receipt?<><p>{item.status==="VERIFIED"?"External readback matched the intent.":item.status==="REJECTED"?"Execution was blocked.":"Execution could not be confirmed as requested."}</p>
     <Json value={item.receipt.verification}/><div className="button-row"><button className="secondary" disabled={busy} onClick={async()=>{setBusy(true);setError("");try{setChecks(await api("/v2/intents/"+id+"/verify"))}catch(e){setError(err(e))}finally{setBusy(false)}}}>Verify evidence now</button>
      <button className="secondary" onClick={()=>download(item.receipt,"tracy-receipt.json")}>Download receipt</button></div>
     {checks&&<Json value={checks}/>}</>:<p>{item.status==="UNCERTAIN"?"The external result is uncertain. Tracy keeps the reservation and checks the provider; it does not repeat the write.":"Waiting for approval, execution or external evidence."}</p>}
    <Link to={"/control/agents/"+item.agent_id}>Open agent policy and export its audit trail →</Link></section>
  </>}
 </>;
}

export function ControlResources(){
 const [items,setItems]=useState<Resource[]>([]),[error,setError]=useState("");
 useEffect(()=>{void api<{items:Resource[]}>("/v2/resources").then(r=>setItems(r.items)).catch(e=>setError(err(e)))},[]);
 return <><h1>Execution resources</h1><p>These resources are assigned to your workspace by the server operator. Agents cannot add arbitrary URLs or read provider credentials.</p><ErrorNotice error={error}/>
  <div className="catalog-grid">{items.map(r=><section className="panel editor" key={r.id}><h2>{r.label}</h2><code>{r.id}</code>
    <Status value={r.configured?"CONFIGURED":"NOT_CONFIGURED"}/><p>{r.actions.join(", ")}</p><p>{r.trust_boundary}</p><p className="muted">{r.unit_description}</p></section>)}</div>
  <p>Local test resources demonstrate the contract. A real GitHub/API connection requires operator configuration and a dedicated credential.</p></>;
}

export function ControlIntegrations(){
 return <><h1>Connect your agent to Tracy</h1><section className="panel editor"><h2>Python SDK</h2>
  <p>Create a protected identity, save its key file, configure a policy and grant a task. The agent receives only that identity and task ID.</p>
  <Json value={{agent_environment:["TRACY_AGENT_KEY_FILE","TRACY_TASK_ID","TRACY_BASE_URL"],never_give_agent:["Wallet private key","Provider API tokens","Database credentials","Owner management API key"]}}/>
  <pre className="control-json">{'from sdk.tracy import AgentIdentity, Tracy\n\ntracy = Tracy(task_id="OWNER_GRANTED_TASK_ID")\nagent = tracy.protect(AgentIdentity.from_file("tracy-agent.json"))\n\nresult = agent.intent(\n    "database.insert", "demo-records",\n    {"record": {"message": "Task completed"}},\n    request_id="job_001",\n)\n# Reuse request_id for retries. AWAITING_APPROVAL means wait for a human.\nprint(agent.status(result["intent_id"]))'}</pre></section>
  <section className="panel editor control-section"><h2>MCP</h2><p>Run the stdio server in the agent environment. It exposes intent submission and status lookup; approval and policy editing stay in the owner console.</p>
  <Json value={{mcpServers:{tracy:{command:"python",args:["-m","sdk.tracy.mcp"],env:{TRACY_AGENT_KEY_FILE:"/absolute/path/tracy-agent.json",TRACY_TASK_ID:"OWNER_GRANTED_TASK_ID",TRACY_BASE_URL:"http://127.0.0.1:8000"}}}}}/>
  <p>MCP protocol: 2025-11-25. Launch from the installed package or project directory.</p></section>
  <section className="panel editor control-section"><h2>LangChain / LangGraph</h2><pre className="control-json">{'from sdk.tracy.langchain import tools\n\nprotected_tools = tools(agent, [{\n    "name": "save_result",\n    "description": "Save a task result through Tracy approval",\n    "action": "database.insert",\n    "resource_id": "demo-records",\n}])\n# Supply protected_tools to your framework instead of direct execution tools.'}</pre>
  <p>Install langchain-core in the agent environment. The adapter supplies standard structured tools for LangChain/LangGraph.</p></section>
  <section className="panel editor control-section"><h2>Enforcement boundary</h2><p>Tracy controls the keys and connections behind its execution resources.
    A wrapper cannot revoke credentials the agent already possesses. Run the agent separately from Tracy, remove direct execution tools and provider credentials,
    and enforce network access restrictions in your deployment. The operator remains trusted.</p>
    <p>Native Devnet SOL, database inserts, GitHub draft PRs and APIs with an evidence-readback contract are implemented.
    SPL/USDC transfers and swaps require separate vetted adapters; unsupported actions are denied.</p></section></>;
}
