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

const statsEl = document.getElementById("stats");
const ledgerCountEl = document.getElementById("ledger-count");
const auditOverlay = document.getElementById("audit-overlay");
const auditListEl = document.getElementById("audit-list");
const auditFiltersEl = document.getElementById("audit-filters");
const auditChainEl = document.getElementById("audit-chain");
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

/* ---- evidence mini-charts ------------------------------------------------
 * Rules adopted from the AGC chart spec (v1.1), scoped to inline SVG:
 * charts carry ONLY numbers already present in the card (no invented data),
 * one semantic color, no gradients/3D, one conclusion per chart, and every
 * rendered value matches the text next to it. */

function svgSparkline(points, opts) {
  // Pure geometry only - labels live in an HTML axis row BELOW the svg, so
  // text and data points can never collide (AGC 13: no element overlap).
  const w = 300, h = 72, pad = 6;
  const vals = points.map(p => p.v);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = (max - min) || 1;
  const step = (w - pad * 2) / (points.length - 1 || 1);
  const coords = points.map((p, i) => [
    Math.round((pad + i * step) * 10) / 10,
    Math.round((h - pad - (p.v - min) / span * (h - pad * 2)) * 10) / 10,
  ]);
  const line = coords.map(c => c.join(",")).join(" ");
  const last = coords[coords.length - 1];
  const hot = opts && opts.hotLast;
  const lastDot = `<circle cx="${last[0]}" cy="${last[1]}" r="4.5"
      fill="${hot ? "var(--over)" : "var(--accent)"}" />`;
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" role="img"
      aria-label="${esc(opts.aria || "trend")}">
      <polyline points="${line}" fill="none" stroke="var(--accent)"
        stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />
      ${lastDot}
    </svg>`;
}

function sparkAxis(firstLabel, lastLabel) {
  return `<div class="spark-axis"><span>${esc(firstLabel)}</span><span>${esc(lastLabel)}</span></div>`;
}

function compareBars(before, after) {
  const afterPct = Math.max(4, Math.round(after / before * 100));
  return `<div class="compare-bars" role="img" aria-label="before ${money(before)} versus after ${money(after)}">
      <div class="cb-row"><span class="cb-label">now</span>
        <div class="cb-track"><div class="cb-fill cb-before" style="width:100%"></div></div>
        <b class="cb-val">${money(before)}</b></div>
      <div class="cb-row"><span class="cb-label">after</span>
        <div class="cb-track"><div class="cb-fill cb-after" style="width:${afterPct}%"></div></div>
        <b class="cb-val">${money(after)}</b></div>
    </div>`;
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
        ${compareBars(card.monthly_before, card.monthly_after)}
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
        ${compareBars(card.monthly_before, card.monthly_after)}
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
        <p class="meta">Largest line: <strong>${esc(card.providers.slice(0, 8).reduce((a, b) => a.amount >= b.amount ? a : b).name)}</strong></p>
        <ul>${card.providers.slice(0, 6).map(p =>
          `<li>${esc(p.name)} — ${money(p.amount)}${p.delta_pct ? ` (${p.delta_pct > 0 ? "+" : ""}${p.delta_pct}%)` : ""}</li>`).join("")}
        </ul>
      </div>`;
    }
    case "crossfoot":
      return `<div class="card${card.ok ? "" : " failed"}">
        <span class="badge ${card.ok ? "ok" : "over"}">${card.ok ? "reconciled" : "FAILED"}</span>
        <h3>Bill crossfoot</h3>
        <ul>
          <li>Rule 1: quantity x unit cost = line amount (every line)</li>
          <li>Rule 2: line amounts sum to the monthly bill (every bill)</li>
        </ul>
        <p class="meta">${card.lines_checked} line items · ${card.bills_checked} bills ·
          ${card.providers_checked} providers · failures: <strong>${card.failures.length}</strong></p>
        <p class="note">Every number on this page reconciles with every other -
        verified live, not claimed.</p>
      </div>`;
    case "provider-detail": {
      const pts = Object.entries(card.monthly).map(([m, v]) => ({ month: m, v: v }));
      const prevVal = pts.length >= 2 ? pts[pts.length - 2].v : null;
      const deltaTxt = card.delta_pct !== null && card.delta_pct !== undefined
        ? `${card.delta_pct > 0 ? "+" : ""}${card.delta_pct}% vs ${esc(card.prev_month)}`
        : "";
      return `<div class="card">
        <span class="badge conf">${esc(card.month)}</span>
        <h3>${esc(card.name)}</h3>
        <p class="amount">${money(card.latest)}</p>
        ${deltaTxt ? `<p class="meta">${deltaTxt}${prevVal ? ` (was ${money(prevVal)})` : ""}</p>` : ""}
        ${svgSparkline(pts, { aria: card.name + " monthly spend trend" })}
        ${sparkAxis(pts[0].month.slice(2), pts[pts.length - 1].month.slice(2))}
        <p class="note">Six-month spend trend, from the same sample ledger every
        other number on this page comes from.</p>
      </div>`;
    }
    case "unit":
      return `<div class="card">
        <span class="badge conf">unit economics</span>
        <h3>Cost per 1K tasks</h3>
        ${card.providers.map(r => {
          const last = r.points[r.points.length - 1];
          const first = r.points[0];
          const tone = r.canary ? "var(--over)" : "var(--accent)";
          const windowPct = r.drift && r.drift.since_first_pct !== null
            ? `${r.drift.since_first_pct > 0 ? "+" : ""}${r.drift.since_first_pct}%`
            : "n/a";
          return `<div class="unit-row${r.canary ? " unit-canary" : ""}">
            <div class="unit-head">
              <b>${esc(r.provider)}</b>
              ${r.canary ? ' <span class="badge over">canary</span>' : ""}
            </div>
            <div class="unit-chart">
              <span class="spark-val spark-first">${money(first.cost_per_1k_tasks)}</span>
              ${svgSparkline(r.points.map(p => ({ v: p.cost_per_1k_tasks })), {
                hotLast: r.canary,
                aria: r.provider + " cost per 1K tasks trend",
              })}
              <span class="spark-val spark-last" style="color:${tone}">${money(last.cost_per_1k_tasks)}</span>
            </div>
            <div class="spark-axis"><span>${esc(first.month.slice(2))}</span>
              <b class="unit-drift" style="color:${tone}">${windowPct}</b>
              <span>${esc(last.month.slice(2))}</span></div>
          </div>`;
        }).join("")}
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
    default:
      return "";
  }
}

function addCards(cards) {
  if (!cards || !cards.length) return;
  // A wrapping grid, not a horizontal scroller: cards must never depend on
  // a scroll container's height, mask, or scrollbar to be visible.
  const row = document.createElement("div");
  row.className = "card-grid";
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
  speakReply(data.reply);
  addCards(data.cards);
  updatePipeline(data.cards);
  loadLedger();
}

const AUDIT_GROUPS = [
  { key: "alert",   label: "Alerts",   kinds: ["alert"], tone: "over" },
  { key: "action",  label: "Actions",  kinds: ["propose", "approve", "execute"], tone: "accent" },
  { key: "quiet",   label: "Held",     kinds: ["suppress", "hold"], tone: "warn" },
  { key: "refused", label: "Refusals", kinds: ["refuse", "challenge"], tone: "ok" },
];

function groupOf(kind) {
  const g = AUDIT_GROUPS.find(g => g.kinds.includes(kind));
  return g ? g.key : "action";
}

let auditEntries = [];
let auditFilter = "all";

async function loadLedger() {
  const res = await fetch(`/api/ledger?session_token=${encodeURIComponent(sessionToken || "")}`);
  const data = await res.json();
  auditEntries = data.entries;
  if (ledgerCountEl) ledgerCountEl.textContent = String(auditEntries.length);
}

function auditKindLabel(kind) {
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}

function renderAudit() {
  const rows = auditEntries.filter(e =>
    auditFilter === "all" || groupOf(e.kind) === auditFilter).reverse();
  auditListEl.innerHTML = rows.map(e => `
    <div class="audit-entry">
      <div class="audit-meta">
        <span class="kind ${esc(e.kind)}">${esc(auditKindLabel(e.kind))}</span>
        <span class="audit-ts">#${e.seq} · ${esc(e.ts.replace("T", " ").slice(0, 19))} UTC</span>
      </div>
      <div class="audit-subject"><b>${esc(e.subject)}</b></div>
      <div class="audit-reason">${esc(e.reason)}</div>
      <div class="audit-hash mono" title="hash-chain: tamper-evident">chain ${esc((e.hash || "").slice(0, 12))}</div>
    </div>`).join("")
    || '<p class="side-note">No entries in this view yet.</p>';
}

async function openAudit(filter) {
  auditFilter = filter || "all";
  await loadLedger();
  auditFiltersEl.innerHTML = [{ key: "all", label: "All" }].concat(AUDIT_GROUPS).map(g => {
    const n = g.key === "all" ? auditEntries.length
      : auditEntries.filter(e => g.kinds.includes(e.kind)).length;
    return `<button class="audit-chip${auditFilter === g.key ? " active" : ""}"
              type="button" data-f="${g.key}">${g.label} (${n})</button>`;
  }).join("");
  auditFiltersEl.querySelectorAll("[data-f]").forEach(btn =>
    btn.addEventListener("click", () => {
      auditFilter = btn.dataset.f;
      auditFiltersEl.querySelectorAll(".audit-chip").forEach(c =>
        c.classList.toggle("active", c.dataset.f === auditFilter));
      renderAudit();
    }));
  renderAudit();
  fetch(`/api/ledger/verify?session_token=${encodeURIComponent(sessionToken || "")}`)
    .then(r => r.json())
    .then(v => {
      auditChainEl.innerHTML = v.ok
        ? `<span class="chain-ok">✓ chain verified</span> — ${v.entries} entries, tamper-evident`
        : `<span class="chain-bad">✗ chain broken at #${v.broken_at}</span>`;
    })
    .catch(() => { auditChainEl.textContent = "chain check unavailable"; });
  auditOverlay.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeAudit() {
  auditOverlay.hidden = true;
  document.body.style.overflow = "";
}

/* ---- voice: speak to the agent, hear it answer --------------------------
 * Progressive enhancement via the Web Speech API: the mic button only
 * appears where SpeechRecognition exists, and TTS is a toggle. No
 * dependency, no cloud SDK - the "simulated Alexa+ experience" gets its
 * voice-first interaction shape from the platform itself. */

const ttsBtn = document.getElementById("tts");
let ttsOn = false;

function speakReply(text) {
  if (!ttsOn || !("speechSynthesis" in window) || !text) return;
  try {
    speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    utter.rate = 1.02;
    speechSynthesis.speak(utter);
  } catch (e) { /* speech is enhancement, never load-bearing */ }
}

ttsBtn.addEventListener("click", () => {
  ttsOn = !ttsOn;
  ttsBtn.setAttribute("aria-pressed", String(ttsOn));
  ttsBtn.textContent = ttsOn ? "🔊" : "🔇";
  if (!ttsOn && "speechSynthesis" in window) speechSynthesis.cancel();
});

const micBtn = document.getElementById("mic");
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR && micBtn) {
  micBtn.hidden = false;
  let recognizing = false;
  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onstart = () => { recognizing = true; micBtn.classList.add("listening"); };
  rec.onend = () => { recognizing = false; micBtn.classList.remove("listening"); };
  rec.onerror = () => { recognizing = false; micBtn.classList.remove("listening"); };
  rec.onresult = (event) => {
    const said = event.results[0][0].transcript.trim();
    if (said) { inputEl.value = said; sendBtn.click(); }
  };
  micBtn.addEventListener("click", () => {
    if (recognizing) { rec.stop(); return; }
    try { rec.start(); } catch (e) { /* already started */ }
  });
}

document.getElementById("audit-open").addEventListener("click", () => openAudit("all"));
document.getElementById("audit-close").addEventListener("click", closeAudit);
auditOverlay.addEventListener("click", e => { if (e.target === auditOverlay) closeAudit(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !auditOverlay.hidden) closeAudit(); });

async function boot() {
  await ensureSession();
  // Build the query with URLSearchParams - hand-concatenating broke the URL
  // when session_id was absent ("/api/opening&session_token=..." -> 404),
  // which used to render as a silent empty bubble.
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  params.set("session_token", sessionToken || "");
  const url = "/api/opening?" + params.toString();
  const res = await fetch(url);
  const data = await res.json();
  sessionId = data.session_id;
  localStorage.setItem(SESSION_KEY, sessionId);
  if (!data.reply && !(data.cards || []).length) {
    // A failed opening used to render as a silent empty bubble.
    addMessage("agent", "I could not load my opening briefing (" + res.status
      + "). Reload the page — if it persists, the service is down.");
    loadLedger();
    return;
  }
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
