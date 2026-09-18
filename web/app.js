/* SpendPilot web experience — simulated Alexa+ interaction model.
 * Layout: main conversation column + a standing side rail that shows the
 * action loop (detect -> prove -> propose -> approve -> execute -> receipt),
 * this month's numbers, and the decision ledger. Keyboard is the primary
 * path; voice stays out of the UI until it works everywhere.
 * Icons: Lucide (https://lucide.dev), ISC license. */

const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const newSessionBtn = document.getElementById("new-session");
const ledgerBody = document.getElementById("ledger-body");
const statsEl = document.getElementById("stats");
const pipelineEl = document.getElementById("pipeline");

const SESSION_KEY = "spendpilot.session";
const SESSION_TOKEN_KEY = "spendpilot.sessionToken";
const proofByProposal = {};  // proposal_id -> the proof shown to
                             // the human in this session (feeds the approval artifact)
let sessionId = localStorage.getItem(SESSION_KEY) || null;
let sessionToken = localStorage.getItem(SESSION_TOKEN_KEY) || null;

/* The browser mints an authenticated session once; its token approves
 * actions and pins this browser to its own workspace state file. */
async function ensureSession() {
  if (sessionToken) return;
  const res = await fetch("/api/session", { method: "POST" });
  const data = await res.json();
  sessionToken = data.session_token;
  localStorage.setItem(SESSION_TOKEN_KEY, sessionToken);
}

function money(v) {
  return "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 });
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function evidenceHTML(items) {
  if (!items || !items.length) return "";
  return `<div class="evidence">${items.map(e =>
    `<div><b>${esc(e.signal)}</b> — ${esc(e.value)}<br><span class="src">${esc(e.source)}</span></div>`
  ).join("")}</div>`;
}

/* The side rail's action loop is a read-only visualization of what the
 * conversation produced (the backend ledger is the source of truth).
 * Query-type cards (overview, budget, ...) do not move the loop. */
const PIPELINE_ORDER = ["detect", "prove", "propose", "approve", "execute", "receipt"];

function stepsFor(card) {
  switch (card.type) {
    case "anomaly":
    case "kept":
      return ["detect"];
    case "saving":
      return ["prove", "propose"];
    case "mandate":
      return ["approve"];
    case "receipt":
      return ["execute", "receipt"];
    default:
      return [];
  }
}

function updatePipeline(cards) {
  if (!cards || !pipelineEl) return;
  let furthest = -1;
  for (const card of cards) {
    for (const step of stepsFor(card)) {
      const i = PIPELINE_ORDER.indexOf(step);
      const li = pipelineEl.querySelector(`[data-step="${step}"]`);
      if (li) li.classList.add("reached");
      if (i > furthest) furthest = i;
    }
  }
  pipelineEl.querySelectorAll("li").forEach((li, i) => {
    li.classList.toggle("current", i === furthest);
  });
}

function resetPipeline() {
  if (!pipelineEl) return;
  pipelineEl.querySelectorAll("li").forEach(li => li.classList.remove("reached", "current"));
}

function cardHTML(card) {
  switch (card.type) {
    case "anomaly":
      return `<div class="card">
        <span class="badge ${card.severity}">${esc(card.severity)}</span>
        <span class="badge ${card.confidence}">${esc(card.confidence)} confidence</span>
        <h3>${esc(card.title)}</h3>
        ${evidenceHTML(card.evidence)}
        ${card.action_ids && card.action_ids.length
          ? `<p class="meta proof-hint">Proof is ready — ask me to "prove the saving".</p>` : ""}
      </div>`;
    case "kept":
      return `<div class="card">
        <span class="badge keep">kept on judgment</span>
        <span class="badge ${card.confidence}">${esc(card.confidence)} confidence</span>
        <h3>${esc(card.title)}</h3>
        ${evidenceHTML(card.evidence)}
        <p class="note">${esc(card.judgment)}</p>
      </div>`;
    case "saving":
      if (card.proposal_id) {
        proofByProposal[card.proposal_id] = card;
      }
      return `<div class="card">
        <span class="badge conf">${esc(card.confidence)} confidence</span>
        <h3>${esc(card.title)}</h3>
        <div class="saving-flow">
          <span class="before">${money(card.monthly_before)}/mo</span>
          <span class="arrow">→</span>
          <span class="after">${money(card.monthly_after)}/mo</span>
        </div>
        <p class="meta">Expected saving: <strong>${card.expected_saving_pct}%</strong>
          (${money(card.annual_saving)}/yr)</p>
        ${card.proof_detail ? `<div class="evidence proof-detail">
            <div><b>Target</b> — ${esc(card.proof_detail.resource)}</div>
            ${(card.proof_detail.observations || []).map(o => `<div><b>observed</b> — ${esc(o)}</div>`).join("")}
            ${(card.proof_detail.assumptions || []).map(a => `<div><b>assumed</b> — ${esc(a)}</div>`).join("")}
            <div class="src">pricing basis: ${esc(card.proof_detail.pricing_basis)}</div>
          </div>` : ""}
        <ul>${card.proof_steps.map(s => `<li>${esc(s)}</li>`).join("")}</ul>
        <p class="meta">Risk: ${esc(card.risk)}</p>
        <p class="note">${esc(card.estimate_basis)}</p>
        ${card.proposal_id
          ? `<p class="note action-hint">On the table as <b>${esc(card.proposal_id)}</b> —
             reply <b>"approve"</b> and I will issue a signed, single-use mandate.</p>` : ""}
      </div>`;
    case "mandate": {
      const proof = proofByProposal[card.proposal_id] || {};
      return `<div class="card approval">
        <div class="approval-head">APPROVAL</div>
        <h3>${esc(proof.title || card.scope.operation)}</h3>
        <div class="kv">
          <div><span>Provider</span><b>${esc(card.scope.provider)}</b></div>
          <div><span>Action</span><b>${esc(card.scope.operation)}</b></div>
          ${proof.monthly_before ? `<div><span>Current</span><b>${money(proof.monthly_before)}/mo</b></div>
          <div><span>After</span><b>${money(proof.monthly_after)}/mo</b></div>
          <div><span>Expected saving</span><b class="ok-text">${esc(proof.expected_saving_pct)}%</b></div>`
          : `<div><span>Cap</span><b>${money(card.scope.max_monthly_before)}/mo</b></div>`}
        </div>
        ${(proof.proof_steps || []).map(s => `<div class="check-line">${esc(s)}</div>`).join("")}
        ${proof.risk ? `<p class="meta">Risk: ${esc(proof.risk)}</p>` : ""}
        <div class="auth-block">
          <div class="auth-title">AUTHORIZATION</div>
          <div class="kv">
            <div><span>Scope</span><b>${esc(card.scope.provider)} only</b></div>
            <div><span>Executions</span><b>one</b></div>
            <div><span>Expires</span><b>${esc(card.expires_at.replace("T", " ").slice(0, 19))} UTC</b></div>
            <div><span>Proof hash</span><b class="mono">${esc(card.proof_hash.slice(0, 16))}...</b></div>
            <div><span>Approved by</span><b>${esc(card.approver)}</b></div>
          </div>
          <p class="meta mono">sig ${esc(card.signature.slice(0, 20))}... - HMAC-SHA256, a local stand-in for AP2 credentials</p>
        </div>
        <p class="note">Reply <b>"execute"</b> and the adapter runs — exactly this, once, before it expires. Without this signature, nothing moves.</p>
      </div>`;
    }
    case "receipt":
      return `<div class="card receipt">
        <span class="badge ok">executed</span>
        <span class="badge conf">simulated adapter</span>
        <h3>${esc(card.operation)}</h3>
        <div class="saving-flow">
          <span class="before">${money(card.monthly_before)}/mo</span>
          <span class="arrow">→</span>
          <span class="after">${money(card.monthly_after)}/mo</span>
        </div>
        <ul>${card.changes.map(s => `<li>${esc(s)}</li>`).join("")}</ul>
        <p class="meta">Adapter: ${esc(card.adapter)} · mandate ${esc(card.mandate_id)} ·
          approved by ${esc(card.approver)}</p>
        <p class="note">Rollback: ${esc(card.rollback)}</p>
      </div>`;
    case "mandates": {
      const rows = card.mandates.map(m =>
        `<li><b>${esc(m.mandate_id)}</b> ${esc(m.scope.operation)} —
           <span class="badge ${m.status === "issued" ? "ok" : "conf"}">${esc(m.status)}</span>
           <span class="meta">cap ${money(m.scope.max_monthly_before)}/mo · sig ${esc(m.signature_short)}</span></li>`).join("");
      const props = card.proposals.map(p =>
        `<li><b>${esc(p.proposal_id)}</b> ${esc(p.title)} —
           <span class="badge conf">${esc(p.status)}</span></li>`).join("");
      const receipts = card.receipts.map(r =>
        `<li><b>${esc(r.operation)}</b> via ${esc(r.adapter)} — saved ${money(r.monthly_saving)}/mo
           <span class="meta">(simulated · ${esc(r.executed_at.replace("T", " ").slice(0, 19))} UTC)</span></li>`).join("");
      return `<div class="card">
        <span class="badge conf">actions</span>
        <h3>Proposals · mandates · receipts</h3>
        ${props ? `<p class="meta">Proposals</p><ul>${props}</ul>` : ""}
        ${rows ? `<p class="meta">Mandates</p><ul>${rows}</ul>` : ""}
        ${receipts ? `<p class="meta">Receipts</p><ul>${receipts}</ul>` : ""}
        ${!props && !rows && !receipts ? `<p class="note">Nothing yet — the loop is prove → approve → execute → receipt.</p>` : ""}
      </div>`;
    }
    case "budget": {
      const pct = Math.min(card.used_pct || 0, 100);
      return `<div class="card">
        <span class="badge ${card.status}">budget · ${esc(card.status)}</span>
        <h3>${esc(card.category)}</h3>
        <p class="amount">${money(card.spent)} / ${money(card.monthly_limit)}</p>
        <div class="bar ${card.status}"><span style="width:${pct}%"></span></div>
        <p class="meta">${card.used_pct}% used this month</p>
      </div>`;
    }
    case "overview": {
      const max = Math.max(...card.providers.map(p => p.amount));
      return `<div class="card">
        <span class="badge conf">${esc(card.month)}</span>
        <h3>Total spend</h3>
        <p class="amount">${money(card.total)}</p>
        <p class="meta">${card.delta_pct > 0 ? "+" : ""}${card.delta_pct}% vs ${esc(card.prev_month)}</p>
        <div class="spark">${card.providers.slice(0, 8).map(p =>
          `<span style="height:${Math.max(8, p.amount / max * 100)}%" title="${esc(p.name)} ${money(p.amount)}"></span>`).join("")}
        </div>
        <ul>${card.providers.slice(0, 6).map(p =>
          `<li>${esc(p.name)} — ${money(p.amount)}${p.delta_pct ? ` (${p.delta_pct > 0 ? "+" : ""}${p.delta_pct}%)` : ""}</li>`).join("")}
        </ul>
      </div>`;
    }
    case "unit":
      return `<div class="card">
        <span class="badge conf">unit economics</span>
        <h3>Cost per 1K tasks</h3>
        <ul>${card.providers.map(r => {
          const last = r.points[r.points.length - 1];
          const drift = r.drift && r.drift.mom_pct !== null ? `${r.drift.mom_pct > 0 ? "+" : ""}${r.drift.mom_pct}% MoM` : "n/a";
          return `<li>${esc(r.provider)} — ${money(last.cost_per_1k_tasks)} /1K tasks (${drift})${r.canary ? ' <span class="badge over">canary</span>' : ""}</li>`;
        }).join("")}</ul>
        <p class="note">Total spend is the smoke alarm; cost per task is the canary.</p>
      </div>`;
    case "subscriptions":
      return `<div class="card">
        <span class="badge conf">recurring</span>
        <h3>Subscriptions</h3>
        <ul>${card.items.map(s =>
          `<li>${esc(s.name)} — ${money(s.monthly)}/mo${s.flag === "zombie" ? ' — <span class="badge warn">unused ' + s.last_used_days + "d</span>" : ""}</li>`).join("")}
        </ul>
      </div>`;
    case "ledger":
      return `<div class="card">
        <span class="badge conf">decision ledger</span>
        <h3>Decision ledger</h3>
        <ul>${card.entries.map(e =>
          `<li><b>${esc(e.kind)}</b> ${esc(e.subject)} — ${esc(e.reason)}</li>`).join("")}
        </ul>
        <p class="note">Challenge any entry: "challenge #3" — your overrule becomes my context.</p>
      </div>`;
    default:
      return "";
  }
}

function addCards(cards) {
  if (!cards || !cards.length) return;
  const row = document.createElement("div");
  row.className = "carousel";
  row.innerHTML = cards.map(cardHTML).join("");
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function renderStats(stats) {
  if (!stats) return;
  statsEl.hidden = false;
  document.getElementById("stat-total").textContent = money(stats.total);
  document.getElementById("stat-month").textContent = stats.month;
  document.getElementById("stat-delta").textContent = (stats.delta_pct > 0 ? "+" : "") + stats.delta_pct + "%";
  document.getElementById("stat-anomalies").textContent = stats.anomalies;
  document.getElementById("stat-saving").textContent = money(stats.saving_potential);
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, session_token: sessionToken }),
  });
  return res.json();
}

async function send(text) {
  if (!text.trim()) return;
  addMessage("user", text);
  inputEl.value = "";
  const data = await post("/api/chat", { message: text, session_id: sessionId });
  sessionId = data.session_id;
  localStorage.setItem(SESSION_KEY, sessionId);
  addMessage("agent", data.reply);
  addCards(data.cards);
  updatePipeline(data.cards);
  loadLedger();
}

async function loadLedger() {
  const res = await fetch(`/api/ledger?session_token=${encodeURIComponent(sessionToken || "")}`);
  const data = await res.json();
  ledgerBody.innerHTML = data.entries.map(e =>
    `<div class="ledger-entry">
       <span class="kind ${esc(e.kind)}">${esc(e.kind)} #${e.seq}</span>
       <span class="why"><b>${esc(e.subject)}</b> — ${esc(e.reason)}</span>
     </div>`).join("") || '<p class="why">No decisions recorded yet.</p>';
}

async function boot() {
  await ensureSession();
  const url = "/api/opening" + (sessionId ? `?session_id=${sessionId}` : "")
    + `&session_token=${encodeURIComponent(sessionToken || "")}`;
  const res = await fetch(url);
  const data = await res.json();
  sessionId = data.session_id;
  localStorage.setItem(SESSION_KEY, sessionId);
  renderStats(data.stats);
  addMessage("agent", data.reply);  // the agent speaks first — it does not wait to be asked
  addCards(data.cards);
  updatePipeline(data.cards);
  loadLedger();
}

sendBtn.addEventListener("click", () => send(inputEl.value));
inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter") send(inputEl.value); });

document.querySelectorAll(".chip").forEach(chip =>
  chip.addEventListener("click", () => send(chip.dataset.say)));

newSessionBtn.addEventListener("click", () => {
  localStorage.removeItem(SESSION_KEY);
  sessionId = null;
  chatEl.innerHTML = "";
  statsEl.hidden = true;
  resetPipeline();
  boot();
});

boot();
