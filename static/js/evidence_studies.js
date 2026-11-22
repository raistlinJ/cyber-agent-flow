"use strict";
const byId = id => document.getElementById(id);
const kinds = {playbook: "Playbooks", skill: "Skills", tool: "Evidence tools", lora_suggestion: "LoRA suggestions"};
const selected = new Set();
let items = [];
let timer;
let loading = false;
let waitingFor = null;

function element(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  Object.assign(node, attrs);
  return node;
}
function button(title, fn) {
  const b = element("button", title, {type: "button"});
  b.onclick = async () => {
    b.disabled = true;
    try { await fn(); } catch (error) { byId("message").textContent = error.message; }
    finally { b.disabled = false; }
  };
  return b;
}
async function api(path, payload) {
  const options = payload === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)};
  const response = await fetch("/api/evidence-studies" + path, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "The request failed.");
  return data;
}
function detail(title) {
  const panel = byId("detail");
  panel.hidden = false;
  panel.replaceChildren(element("h2", title));
  panel.focus();
  return panel;
}
async function start(action, payload) {
  const row = await api("/actions/" + action, payload);
  waitingFor = row.status === "running" ? row.id : null;
  byId("message").textContent = row.status === "complete" ? "Saved to runnable experiments." : "CAF is running this stage. You can leave this page and return to it.";
  await refresh();
  if (action === "save") byId("saved-title").scrollIntoView({block:"nearest"});
}
function choose(item) {
  const cb = element("input", undefined, {type:"checkbox", checked:selected.has(item.id)});
  cb.onchange = () => {
    if (cb.checked) selected.add(item.id); else selected.delete(item.id);
    byId("compare").disabled = selected.size < 2;
  };
  const label = element("label");
  label.append(cb, document.createTextNode(item.name));
  return label;
}
function list(target, rows, empty) {
  const panel = byId(target);
  panel.replaceChildren();
  if (!rows.length) panel.append(element("p", empty, {className:"secondary"}));
  for (const item of rows) {
    const row = element("div", undefined, {className:"row"});
    const actions = element("div", undefined, {className:"actions"});
    const complete = item.status === "complete";
    const run = ["baseline","study","run"].includes(item.kind);
    row.append(run && complete ? choose(item) : element("strong", item.name));
    const label = {baseline:"Baseline", study:"Ranked study", analyze:"Analysis", generate:"Candidates", save:"Saved", run:"Experiment run"}[item.kind];
    const when = item.created ? " · " + new Date(item.created).toLocaleString() : "";
    actions.append(element("span", label + " · " + item.status + when, {className:"secondary"}));
    if (complete) {
      actions.append(button("View", () => show(item.id)));
      if (run) actions.append(button("Analyze baseline", () => start("analyze", {source:item.id})));
      if (item.kind === "save") actions.append(button("Run experiment", () => start("run", {source:item.id})));
    } else if (item.status === "interrupted" || item.status === "failed") {
      if (item.error) actions.append(element("span", item.error));
      actions.append(button("Resume",() => start("resume",{id:item.id})));
    }
    row.append(actions); panel.append(row);
  }
}
async function refresh() {
  if (loading) return;
  loading = true;
  clearTimeout(timer);
  try {
    const state = await api("");
    items = state.items;
    const profile = byId("profile"), previous = profile.value;
    profile.replaceChildren(...state.profiles.map(p => element("option", p, {value:p})));
    if (state.profiles.includes(previous)) profile.value = previous;
    byId("new-run").hidden = !state.profiles.length;
    byId("ranked").hidden = !state.profiles.length;
    byId("no-profiles").hidden = !!state.profiles.length;
    list("runs", items.filter(i => ["baseline","study","run"].includes(i.kind)), "Completed and running sessions appear here.");
    list("reviews", items.filter(i => ["analyze","generate"].includes(i.kind)), "Choose Analyze run on a completed baseline to review its evidence.");
    list("saved", items.filter(i => i.kind === "save"), "Select artifacts from a review and save them as an experiment.");
    const finished = items.find(i => i.id === waitingFor && i.status !== "running");
    if (finished) {
      waitingFor = null;
      if (finished.status === "complete") {
        byId("message").textContent = "Stage complete.";
        await show(finished.id);
      } else byId("message").textContent = finished.error || "The job was interrupted.";
    }
    if (items.some(i => i.status === "running")) timer = setTimeout(safeRefresh, 2000);
  } finally { loading = false; }
}
async function safeRefresh() {
  try { await refresh(); } catch (error) { byId("message").textContent = error.message; }
}
function comparison(tableRows) {
  const wrap = element("div", undefined, {className:"wrap"}), table = element("table");
  const header = table.createTHead().insertRow();
  for (const label of ["Run","Condition","Flags credited","Flags in answer","Valid submissions","Incorrect submissions"]) header.append(element("th",label));
  const body = table.createTBody();
  for (const r of tableRows) {
    const row = body.insertRow();
    for (const v of [r.name,r.condition, r.flags_recovered == null ? null : r.flags_recovered + "/" + r.flags_available,
      r.flags_in_answer, r.valid_submissions == null ? null : r.valid_submissions + "/" + r.sessions, r.incorrect_submissions])
      row.append(element("td", v ?? "Unavailable"));
  }
  wrap.append(table); return wrap;
}
function generation(panel, id) {
  panel.append(element("h3", "Candidates to generate"));
  const grid = element("div", undefined, {className:"counts"}), counts = {};
  for (const [key,name] of Object.entries(kinds)) {
    const label = element("label",name), input = element("input",undefined,{type:"number",min:"0",step:"1",value:"1",required:true});
    counts[key]=input; label.append(input);grid.append(label);
  }
  panel.append(grid, button("Generate candidates", async () => {
    for (const input of Object.values(counts)) if (!input.reportValidity()) return;
    await start("generate",{source:id,counts:Object.fromEntries(Object.entries(counts).map(([k,v]) => [k,Number(v.value)]))});
  }));
}
function candidates(panel, id, entries) {
  panel.append(element("h3","Choose artifacts to enable"));
  const choices = [];
  if (!entries.length) panel.append(element("p","No candidates were produced. You can save a control experiment with none enabled."));
  for (const c of entries) {
    const row = element("div", undefined, {className:"candidate"});
    const label = element("label", undefined);
    const cb = element("input",undefined,{type:"checkbox",disabled:!c.eligible,value:c.id});
    label.append(cb, document.createTextNode((c.name || c.id) + " · " + c.kind + " · " + c.status));
    row.append(label);
    if (c.description) row.append(element("p",c.description));
    if (c.preview) {const more = element("details"); more.append(element("summary","Preview"),element("pre",c.preview));row.append(more);}
    choices.push(cb);panel.append(row);
  }
  const name = element("input",undefined,{maxLength:120,required:true});
  const label = element("label","Experiment name");label.append(name);
  panel.append(label, document.createTextNode(" "),button("Add to runnable experiments",async () => {
    if (!name.reportValidity()) return;
    await start("save",{source:id,name:name.value,enabled:choices.filter(c => c.checked && !c.disabled).map(c => c.value)});
  }));
}
async function show(id) {
  const item = await api("/items/" + encodeURIComponent(id));
  const d = item.detail || {};
  const panel = detail(item.name);
  if (d.case) panel.append(element("p",d.case,{className:"secondary"}));
  for (const a of d.analysis || []) panel.append(element("pre",a));
  for (const k of ["baseline","confirmation"]) if (d[k])
    panel.append(element("p",(k === "baseline" ? "Baseline" : "Confirmation") + " · " + d[k].flags_recovered + "/" + d[k].flags_available + " flags credited"));
  if (item.kind === "analyze") generation(panel,item.id);
  if (item.kind === "generate") candidates(panel,item.id,d.candidates || []);
  if (item.kind === "save") panel.append(element("p","Enabled artifacts · " + (d.enabled || []).join(", ")),button("Run experiment",() => start("run",{source:item.id})));
}
byId("baseline").onclick = async () => {
  byId("baseline").disabled = true;
  try { await start("baseline",{profile:byId("profile").value}); } catch (e) { byId("message").textContent=e.message; }
  finally { byId("baseline").disabled = false; }
};
byId("compare").onclick = async () => {
  try {
    const data = await api("/actions/compare",{ids:[...selected]});
    const panel = detail("Run comparison");
    if (new Set(data.rows.map(r => r.package_hash)).size > 1) panel.append(element("p","These runs used different case packages."));
    panel.append(comparison(data.rows));
  } catch(e) { byId("message").textContent=e.message; }
};
for (const [key,name] of Object.entries(kinds)) {
  const label = element("label",name);
  label.append(element("input",undefined,{name:key,type:"number",min:"0",step:"1",value:"1",required:true}));
  byId("study-counts").append(label);
}
async function ranked(action) {
  const form = byId("study-form");
  if (!form.reportValidity()) return;
  const values = new FormData(form);
  const config = {profile:byId("profile").value, counts:Object.fromEntries(Object.keys(kinds).map(k=>[k,Number(values.get(k))])),
    keep_top:Number(values.get("keep_top")), repetitions:Number(values.get("repetitions")), selection:values.get("selection")};
  if (action === "study") return start(action, config);
  const p = await api("/actions/plan",config);
  detail("Study plan").append(element("p",p.repetitions+" repetition(s), up to "+p.max_participant_trials+" participant sessions and "+p.keep_top+" retained artifacts."));
}
byId("plan").onclick = () => ranked("plan").catch(e=>byId("message").textContent=e.message);
byId("study-form").onsubmit = async e => {
  e.preventDefault(); const control=e.submitter; if(control) control.disabled=true;
  try { await ranked("study"); } catch(err) { byId("message").textContent=err.message; } finally { if(control) control.disabled=false; }
};
safeRefresh();
