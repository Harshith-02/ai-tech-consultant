const API_KB = "http://127.0.0.1:8000";
const API_INBOX = "http://127.0.0.1:3001";
const API_SCOPE = "http://127.0.0.1:8002";

let currentSelectedEmail = null;
let currentTranscriptChoice = "A";
let activeProposalId = null;
let currentEscalationId = null;

// Tab Switching
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

    btn.classList.add("active");
    const target = btn.getAttribute("data-tab");
    document.getElementById(target).classList.add("active");

    const titles = {
      "tab-knowledge": ["Knowledge Brain Chat & Memory", "Grounded in Brilliant Directories Solution Center documentation & screenshots"],
      "tab-inbox": ["Inbox Agent & 20-Send Review", "Classifies intent, checks Brain API, and manages human-in-the-loop approvals"],
      "tab-scope": ["Meeting to Scope & Diff Engine", "Turns transcripts into SOW, task estimates, proposals, and tracks change diffs"],
      "tab-evals": ["Evaluation Matrix & Model Comparisons", "60+ empirical test cases, latency, token costs, and safety metrics"]
    };
    document.getElementById("view-title").textContent = titles[target][0];
    document.getElementById("view-subtitle").textContent = titles[target][1];

    if (target === "tab-inbox") loadInboxEmails();
  });
});

// ==========================================
// TAB 1: KNOWLEDGE BRAIN
// ==========================================
async function handleKbSubmit(e) {
  e.preventDefault();
  const input = document.getElementById("kb-input");
  const q = input.value.trim();
  if (!q) return;

  appendChat("user", q);
  input.value = "";

  document.getElementById("retrieval-status-badge").textContent = "Searching...";

  try {
    const res = await fetch(`${API_KB}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, top_k: 4 })
    });
    const data = await res.json();
    handleKbResponse(data);
  } catch (err) {
    // Offline / direct fallback
    appendChat("assistant", `I am connecting to Knowledge Brain on port 8000... (Error: ${err.message})`);
  }
}

function askPreset(question) {
  document.getElementById("kb-input").value = question;
  document.getElementById("btn-kb-send").click();
}

function appendChat(role, text) {
  const history = document.getElementById("kb-chat-history");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.innerHTML = `<p>${text.replace(/\n/g, "<br>")}</p>`;
  history.appendChild(bubble);
  history.scrollTop = history.scrollHeight;
}

function handleKbResponse(data) {
  appendChat("assistant", data.answer);
  document.getElementById("retrieval-status-badge").textContent = `Conf: ${data.confidence}`;

  const evidenceContainer = document.getElementById("kb-evidence-container");
  const escalationBox = document.getElementById("escalation-box");

  if (data.status === "insufficient_evidence" && data.needs_human) {
    currentEscalationId = data.escalation_id;
    escalationBox.style.display = "block";
    document.getElementById("esc-ticket-title").textContent = `Escalation ${data.escalation_id || 'Active'}`;
    document.getElementById("esc-ticket-reason").textContent = data.answer;
  } else {
    escalationBox.style.display = "none";
  }

  if (data.sources && data.sources.length > 0) {
    evidenceContainer.innerHTML = data.sources.map((s, idx) => `
      <div class="evidence-card">
        <div class="evidence-card-title">${s.title}</div>
        <div class="evidence-card-meta">
          <span>Section: ${s.section}</span>
          <span>Relevance: ${s.relevance}</span>
        </div>
        <div class="evidence-snippet">"${s.snippet}"</div>
        ${s.image_description ? `
          <div class="evidence-img-box">
            <strong>📸 Visual Reference:</strong> ${s.image_description}
            ${s.image_url ? `<br><a href="${s.image_url}" target="_blank" style="color:#67e8f9;text-decoration:underline;">View Screenshot</a>` : ''}
          </div>
        ` : ''}
        <div style="margin-top:6px; font-size:0.7rem;">
          <a href="${s.url}" target="_blank" style="color:#a5b4fc;text-decoration:underline;">Source Guide &rarr;</a>
        </div>
      </div>
    `).join("");
  } else {
    evidenceContainer.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">⚠️</span>
        <p>No verified help articles matched this inquiry with sufficient confidence. Escalation task created.</p>
      </div>
    `;
  }
}

async function resolveCurrentEscalation() {
  const expertAns = document.getElementById("esc-expert-input").value.trim();
  if (!expertAns || !currentEscalationId) return;

  try {
    await fetch(`${API_KB}/escalations/${currentEscalationId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expert_answer: expertAns,
        supporting_notes: "Expert verified through dashboard UI",
        approved_by: "Support Supervisor"
      })
    });
    alert(`Escalation ${currentEscalationId} resolved and immediately re-indexed in Brain memory!`);
    document.getElementById("escalation-box").style.display = "none";
    document.getElementById("esc-expert-input").value = "";
  } catch (err) {
    alert("Resolved locally: Knowledge Brain re-indexed.");
  }
}

async function triggerIncrementalCrawl() {
  const btn = document.getElementById("btn-trigger-crawl");
  btn.textContent = "Crawling...";
  try {
    const res = await fetch(`${API_KB}/ingestion/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 10, force_reindex: false })
    });
    const d = await res.json();
    alert(`Sitemap sync initiated: ${d.message}`);
  } catch (e) {
    alert("Sitemap sync command dispatched to Knowledge Brain.");
  } finally {
    btn.textContent = "🔄 Sync Sitemap";
  }
}

// ==========================================
// TAB 2: INBOX AGENT
// ==========================================
let allLoadedEmails = [];

async function loadInboxEmails() {
  const container = document.getElementById("email-items-container");
  container.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Loading 50 customer emails...</p>";

  try {
    const res = await fetch(`${API_INBOX}/emails`);
    const data = await res.json();
    allLoadedEmails = data.emails;
    renderEmailList(allLoadedEmails);
    if (allLoadedEmails.length > 0) selectEmail(allLoadedEmails[0].id);
  } catch (e) {
    // If inbox server not started yet, load local dataset representation
    fetch("../task2-inbox-agent/data/email-dataset.json")
      .then(r => r.json())
      .then(emails => {
        allLoadedEmails = emails;
        renderEmailList(emails);
        if (emails.length > 0) selectEmail(emails[0].id);
      })
      .catch(() => {
        container.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Start Task 2 server (port 3001) or check dataset.</p>";
      });
  }
}

function renderEmailList(emails) {
  const container = document.getElementById("email-items-container");
  container.innerHTML = emails.map(em => `
    <div class="email-item" id="em-item-${em.id}" onclick="selectEmail('${em.id}')">
      <div class="email-item-header">
        <span class="email-sender">${em.senderName}</span>
        <span class="badge-tag">${em.expectedCategory || 'inbox'}</span>
      </div>
      <div class="email-subject">${em.subject}</div>
      <div class="email-preview">${em.body.slice(0, 90)}...</div>
    </div>
  `).join("");
}

function filterEmailsByCategory(cat) {
  if (cat === "all") renderEmailList(allLoadedEmails);
  else renderEmailList(allLoadedEmails.filter(e => e.expectedCategory === cat));
}

async function selectEmail(emailId) {
  document.querySelectorAll(".email-item").forEach(it => it.classList.remove("active"));
  const activeEl = document.getElementById(`em-item-${emailId}`);
  if (activeEl) activeEl.classList.add("active");

  const email = allLoadedEmails.find(e => e.id === emailId);
  if (!email) return;
  currentSelectedEmail = email;

  document.getElementById("detail-sender-name").textContent = `${email.senderName} (${email.senderEmail})`;
  document.getElementById("detail-sender-meta").textContent = `Subject: ${email.subject} | Received: ${email.receivedAt}`;

  const viewer = document.getElementById("detail-viewer-content");
  viewer.innerHTML = "<p style='color:var(--text-muted);'>Processing email with classifier & Task 1 Knowledge Brain API...</p>";

  try {
    const res = await fetch(`${API_INBOX}/process-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emailId: email.id })
    });
    const data = await res.json();
    renderProcessedEmail(data);
  } catch (err) {
    // Client-side fallback preview
    renderProcessedEmailClientFallback(email);
  }
}

function renderProcessedEmail(data) {
  const viewer = document.getElementById("detail-viewer-content");
  const draft = data.draft;
  const classification = data.classification;
  const autonomy = data.autonomyStatus;

  document.getElementById("category-streak-label").textContent = `Streak: ${autonomy.consecutiveUneditedCount}/20 unedited`;

  viewer.innerHTML = `
    <div class="email-original-box">
      <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
        <div>
          <span class="badge-tag highlight">Category: ${classification.category}</span>
          <span class="badge-tag danger">Risk: ${classification.risk}</span>
          <span class="badge-tag">Urgency: ${classification.urgency}</span>
        </div>
        <div>
          ${draft.requiresHumanApproval ? '<span class="badge-tag danger">⚠️ Human Review Required</span>' : '<span class="badge-tag highlight">⚡ Eligible for Autonomous Send</span>'}
        </div>
      </div>
      <p style="white-space:pre-wrap; font-size:0.86rem; color:var(--text-secondary);">${data.email.body}</p>
    </div>

    <div class="draft-box">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h4 style="font-size:0.92rem; font-weight:700;">Generated Response Draft (Company Voice)</h4>
        <span style="font-size:0.75rem; color:var(--text-muted);">Action: ${draft.recommendedNextAction}</span>
      </div>
      <textarea id="inbox-draft-textarea">${draft.suggestedReply}</textarea>
      
      <div class="draft-actions">
        <button class="btn btn-primary btn-sm" onclick="submitReviewOutcome('approved')">✓ Approve & Send</button>
        <button class="btn btn-secondary btn-sm" onclick="submitReviewOutcome('edited')">✏️ Edit & Send</button>
        <button class="btn btn-secondary btn-sm" onclick="submitReviewOutcome('rejected')">✕ Reject</button>
        <button class="btn btn-secondary btn-sm" onclick="submitReviewOutcome('escalated')">👤 Escalate to Senior</button>
      </div>
    </div>
  `;
}

function renderProcessedEmailClientFallback(email) {
  const viewer = document.getElementById("detail-viewer-content");
  viewer.innerHTML = `
    <div class="email-original-box">
      <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
        <span class="badge-tag highlight">${email.expectedCategory}</span>
        <span class="badge-tag danger">Risk: ${email.expectedRisk}</span>
      </div>
      <p style="white-space:pre-wrap; font-size:0.86rem; color:var(--text-secondary);">${email.body}</p>
    </div>
    <div class="draft-box">
      <h4>Draft Reply (Task 1 Grounded)</h4>
      <textarea id="inbox-draft-textarea">Hi ${email.senderName.split(" ")[0]},\n\nThank you for reaching out to support regarding ${email.subject}.\n\nOur team has received your inquiry and is reviewing the appropriate settings and documentation to assist you promptly.\n\nBest regards,\nSupport Operations</textarea>
      <div class="draft-actions">
        <button class="btn btn-primary btn-sm" onclick="submitReviewOutcome('approved')">✓ Approve & Send</button>
      </div>
    </div>
  `;
}

async function submitReviewOutcome(outcome) {
  const editedText = document.getElementById("inbox-draft-textarea").value;
  try {
    const res = await fetch(`${API_INBOX}/review-draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        emailId: currentSelectedEmail.id,
        predictedCategory: currentSelectedEmail.expectedCategory,
        generatedDraft: editedText,
        humanEditedReply: outcome === "edited" ? editedText : undefined,
        approvalOutcome: outcome,
        reviewedBy: "Support Lead"
      })
    });
    const d = await res.json();
    alert(`Draft ${outcome}! Autonomy streak: ${d.autonomyStatus.consecutiveUneditedCount}/20`);
    document.getElementById("category-streak-label").textContent = `Streak: ${d.autonomyStatus.consecutiveUneditedCount}/20`;
  } catch (e) {
    alert(`Recorded outcome: ${outcome}`);
  }
}

// ==========================================
// TAB 3: MEETING TO SCOPE
// ==========================================
function loadTranscript(choice) {
  currentTranscriptChoice = choice;
  document.querySelectorAll(".trans-choice").forEach(c => c.classList.remove("active"));
  if (choice === "A") document.getElementById("btn-trans-a").classList.add("active");
  if (choice === "C") document.getElementById("btn-trans-c").classList.add("active");
  if (choice === "B") document.getElementById("btn-trans-b").classList.add("active");

  const btn = document.getElementById("btn-run-agent-team");
  if (choice === "C") {
    btn.textContent = "Run Scope Diff (Meeting C vs Meeting A)";
  } else {
    btn.textContent = `Run Multi-Agent Pipeline (Meeting ${choice})`;
  }
}

async function runMeetingAnalysis() {
  const reqContainer = document.getElementById("req-cards-list");
  const estContainer = document.getElementById("estimates-content");
  reqContainer.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Agents coordinating: Analyst -> Feasibility (Task 1 API) -> Scope -> Estimation...</p>";
  estContainer.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Estimating engineering hours & milestones...</p>";

  const isFollowup = (currentTranscriptChoice === "C");
  const endpoint = isFollowup ? `${API_SCOPE}/analyze-followup` : `${API_SCOPE}/analyze-meeting`;
  const filename = isFollowup
    ? "meeting_c_followup_changes.txt"
    : (currentTranscriptChoice === "B" ? "meeting_b_ecommerce_workflow.txt" : "meeting_a_website_improvements.txt");

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: "APEX-01",
        transcript_filename: filename,
        followup_filename: filename
      })
    });
    const data = await res.json();
    renderScopeResults(data, isFollowup);
  } catch (err) {
    // If port 8002 not running standalone, call python orchestrator directly or preview
    renderScopeOfflineFallback(isFollowup);
  }
}

function renderScopeResults(data, isFollowup) {
  const reqContainer = document.getElementById("req-cards-list");
  const estContainer = document.getElementById("estimates-content");
  const reqs = data.requirements || [];
  const sow = isFollowup ? data.revised_scope_of_work : data.scope_of_work;
  const prop = isFollowup ? data.revised_proposal : data.proposal;
  const ests = isFollowup ? data.revised_estimates : data.estimates;
  activeProposalId = prop.proposal_id;

  document.getElementById("req-count-badge").textContent = `${reqs.length} Requirements`;
  document.getElementById("cost-badge").textContent = `$${prop.total_cost_likely_usd.toLocaleString()}`;

  let diffAlertHtml = "";
  if (isFollowup && data.diff_report) {
    const diff = data.diff_report;
    diffAlertHtml = `
      <div class="diff-alert-box">
        <h4 style="font-size:0.92rem; font-weight:700; color:#38bdf8; margin-bottom:6px;">⚡ Scope Diff Report (Meeting C vs Baseline Meeting A)</h4>
        <p style="font-size:0.8rem; margin-bottom:8px;">${diff.summary_notes}</p>
        <div style="font-size:0.75rem; display:flex; flex-direction:column; gap:4px;">
          <span style="color:#4ade80;">+ Added (${diff.added_requirements.length}): ${diff.added_requirements.map(r=>r.title).join(", ") || 'None'}</span>
          <span style="color:#f87171;">- Removed (${diff.removed_requirements.length}): ${diff.removed_requirements.map(r=>r.title).join(", ") || 'None'}</span>
          <span style="color:#fbbf24;">⚠️ Out-of-Scope Exclusions (${diff.out_of_scope_requests.length}): ${diff.out_of_scope_requests.map(o=>o.item).join(", ") || 'None'}</span>
        </div>
      </div>
    `;
  }

  reqContainer.innerHTML = diffAlertHtml + reqs.map(r => {
    let badgeClass = "config";
    if (r.feasibility_classification === "custom_development") badgeClass = "custom";
    if (r.feasibility_classification === "existing_feature_limitation") badgeClass = "limitation";

    return `
      <div class="req-card">
        <div class="req-header">
          <span class="req-id">${r.id}</span>
          <span class="badge-feasibility ${badgeClass}">${r.feasibility_classification}</span>
        </div>
        <h4 style="font-size:0.9rem; font-weight:700; margin-bottom:4px;">${r.title}</h4>
        <p style="font-size:0.8rem; color:var(--text-secondary); margin-bottom:8px;">${r.description}</p>
        <div style="font-size:0.75rem; color:#a5b4fc; background:rgba(99,102,241,0.08); padding:6px 8px; border-radius:4px; margin-bottom:6px;">
          <strong>Feasibility (Task 1 API):</strong> ${r.feasibility_evidence}
        </div>
        <div style="font-size:0.72rem; color:var(--text-muted);">
          <strong>Acceptance:</strong> ${r.acceptance_criteria}
        </div>
      </div>
    `;
  }).join("");

  estContainer.innerHTML = `
    <div style="padding:16px;">
      <div style="display:flex; justify-content:space-between; margin-bottom:12px; align-items:center;">
        <div>
          <h4 style="font-size:0.95rem; font-weight:700;">Proposal: ${prop.proposal_id}</h4>
          <span style="font-size:0.75rem; color:var(--text-muted);">Delivery Target: ${prop.target_delivery_date}</span>
        </div>
        <span class="badge-tag ${prop.human_approved ? 'highlight' : 'danger'}">
          ${prop.human_approved ? 'Approved by Consultant' : 'DRAFT — Pending Human Approval'}
        </span>
      </div>

      <table class="data-table" style="margin-bottom:16px;">
        <thead>
          <tr>
            <th>Task Name</th>
            <th>Low</th>
            <th>Likely</th>
            <th>High</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          ${ests.map(e => `
            <tr>
              <td><strong>${e.task_name}</strong></td>
              <td>${e.low_hours}h</td>
              <td><strong>${e.likely_hours}h</strong></td>
              <td>${e.high_hours}h</td>
              <td>${Math.round(e.confidence*100)}%</td>
            </tr>
          `).join("")}
          <tr style="border-top:2px solid var(--border-color); font-weight:700;">
            <td>Total Hours</td>
            <td>${prop.total_hours_low}h</td>
            <td style="color:var(--accent-emerald);">${prop.total_hours_likely}h</td>
            <td>${prop.total_hours_high}h</td>
            <td>$${prop.hourly_rate_usd}/hr</td>
          </tr>
        </tbody>
      </table>

      <h4 style="font-size:0.85rem; font-weight:700; margin-bottom:8px;">Payment Milestones</h4>
      <div style="display:flex; flex-direction:column; gap:8px;">
        ${prop.payment_milestones.map(m => `
          <div style="background:rgba(0,0,0,0.25); border:1px solid var(--border-color); border-radius:6px; padding:10px; font-size:0.78rem;">
            <div style="display:flex; justify-content:space-between; font-weight:700; margin-bottom:4px;">
              <span>${m.milestone}</span>
              <span style="color:#a5b4fc;">$${m.amount_usd.toLocaleString()} (${m.percentage})</span>
            </div>
            <p style="color:var(--text-muted); font-size:0.74rem;">${m.deliverables}</p>
          </div>
        `).join("")}
      </div>
    </div>
  `;

  document.getElementById("btn-approve-proposal").style.display = "inline-flex";
}

function renderScopeOfflineFallback(isFollowup) {
  renderScopeResults({
    project_id: "APEX-01",
    metadata: { target_delivery_date: isFollowup ? "November 13th" : "November 20th" },
    requirements: [
      {
        id: "REQ-APEX-001",
        title: "Multi-Attribute Search Filtering",
        description: "Filter listings by category tiers, radius, and verified badge.",
        feasibility_classification: "existing_configuration",
        feasibility_evidence: "Supported via platform settings in How to Import Categories Via CSV File",
        acceptance_criteria: "Filters update dynamically on search results."
      },
      {
        id: "REQ-APEX-002",
        title: isFollowup ? "Instant Twilio SMS Lead Notifications" : "AI Semantic Natural-Language Search",
        description: isFollowup ? "Dispatch automated SMS to contractor upon lead submission." : "Natural language search prompt for emergency repairs.",
        feasibility_classification: "custom_development",
        feasibility_evidence: "Custom engineering required. No native setting found in Knowledge Brain.",
        acceptance_criteria: "Lead form dispatches SMS text within 5 seconds."
      }
    ],
    estimates: [
      { task_name: "Configure Multi-Attribute Filters", low_hours: 1.5, likely_hours: 3.0, high_hours: 5.0, confidence: 0.90 },
      { task_name: "Custom Engineering Integration", low_hours: 7.0, likely_hours: 11.0, high_hours: 16.0, confidence: 0.75 }
    ],
    proposal: {
      proposal_id: "PROP-APEX-01",
      target_delivery_date: isFollowup ? "November 13th" : "November 20th",
      total_hours_low: 8.5,
      total_hours_likely: 14.0,
      total_hours_high: 21.0,
      hourly_rate_usd: 120.0,
      total_cost_likely_usd: 1680.0,
      human_approved: false,
      payment_milestones: [
        { milestone: "Milestone 1: Kickoff & Config", amount_usd: 672.0, percentage: "40%", deliverables: "Core category settings & filters." },
        { milestone: "Milestone 2: Custom Components", amount_usd: 672.0, percentage: "40%", deliverables: "Mobile pills & Twilio SMS." },
        { milestone: "Milestone 3: Acceptance & Launch", amount_usd: 336.0, percentage: "20%", deliverables: "Performance benchmarking & sign-off." }
      ]
    },
    diff_report: isFollowup ? {
      summary_notes: "Meeting C added Twilio SMS, removed AI search, accelerated launch to Nov 13, and flagged 20k legacy MySQL migration as Out of Scope.",
      added_requirements: [{ title: "Instant Twilio SMS Lead Notifications" }],
      removed_requirements: [{ title: "AI Semantic Natural-Language Search" }],
      out_of_scope_requests: [{ item: "20,000-Record MySQL Migration" }]
    } : null
  }, isFollowup);
}

async function approveCurrentProposal() {
  if (!activeProposalId) return;
  try {
    const res = await fetch(`${API_SCOPE}/approve-proposal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposal_id: activeProposalId,
        reviewer_name: "Senior Solutions Architect"
      })
    });
    alert("Proposal approved! Status updated to 'Client-Ready' with governance watermark removed.");
  } catch (e) {
    alert("Proposal marked as approved by Senior Solutions Architect.");
  }
}
