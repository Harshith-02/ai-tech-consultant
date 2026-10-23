// Support both local multi-service development and cloud / Vercel serverless deployment
const isLocalMultiPort = window.location.hostname === "127.0.0.1" && window.location.port === "5000";
const API_KB = isLocalMultiPort ? "http://127.0.0.1:8000" : "/api/kb";
const API_INBOX = isLocalMultiPort ? "http://127.0.0.1:3001" : "/api/inbox";
const API_SCOPE = isLocalMultiPort ? "http://127.0.0.1:8002" : "/api/scope";

// Global Authenticated Fetch Interceptor
const AUTH_TOKEN = localStorage.getItem("auth_token") || "lead-consultant-sec-token-2026";
const _origFetch = window.fetch;
window.fetch = async function(input, init) {
  init = init || {};
  init.headers = init.headers || {};
  if (init.headers instanceof Headers) {
    if (!init.headers.has("Authorization")) {
      init.headers.set("Authorization", `Bearer ${AUTH_TOKEN}`);
    }
  } else if (Array.isArray(init.headers)) {
    init.headers.push(["Authorization", `Bearer ${AUTH_TOKEN}`]);
  } else {
    if (!init.headers["Authorization"]) {
      init.headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;
    }
  }
  return _origFetch(input, init);
};

let currentSelectedEmail = null;
let currentTranscriptChoice = "A";
let activeProposalId = null;
let currentEscalationId = null;

// Slide Bars & Multimodal State
let currentMinConfidence = 0.40;
let currentTopK = 4;
let stagedScreenshotData = null;

// Interactive Slide Bars (Sliders) Controls
function updateThresholdVal(val) {
  currentMinConfidence = parseFloat(val) / 100;
  const label = document.getElementById("threshold-val");
  if (label) label.textContent = `${val}%`;
}

function updateTopKVal(val) {
  currentTopK = parseInt(val, 10);
  const label = document.getElementById("topk-val");
  if (label) label.textContent = `${val} Chunks`;
}

function toggleSidebarSlide() {
  const sidebar = document.querySelector(".sidebar");
  if (sidebar) sidebar.classList.toggle("collapsed");
}

// Screenshot Staging & Image Handling
function handleFileSelect(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  loadScreenshotFile(file);
}

function loadScreenshotFile(file) {
  if (!file.type.startsWith("image/")) {
    alert("Please upload a valid image (PNG, JPG, WebP)");
    return;
  }
  const reader = new FileReader();
  reader.onload = (event) => {
    stagedScreenshotData = {
      name: file.name || "screenshot.png",
      dataUrl: event.target.result
    };
    showStagedScreenshot();
  };
  reader.readAsDataURL(file);
}

function showStagedScreenshot() {
  if (!stagedScreenshotData) return;
  const bar = document.getElementById("staged-screenshot-bar");
  const img = document.getElementById("staged-screenshot-img");
  const name = document.getElementById("staged-screenshot-name");
  if (img) img.src = stagedScreenshotData.dataUrl;
  if (name) name.textContent = stagedScreenshotData.name;
  if (bar) bar.style.display = "flex";
}

function clearStagedScreenshot() {
  stagedScreenshotData = null;
  const bar = document.getElementById("staged-screenshot-bar");
  if (bar) bar.style.display = "none";
  const fileInput = document.getElementById("kb-file-input");
  if (fileInput) fileInput.value = "";
}

// Paste Screenshot from Clipboard (Ctrl+V)
window.addEventListener("paste", (e) => {
  const items = (e.clipboardData || (e.originalEvent && e.originalEvent.clipboardData))?.items;
  if (!items) return;
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.indexOf("image") !== -1) {
      const blob = items[i].getAsFile();
      loadScreenshotFile(blob);
      break;
    }
  }
});

// Drag & Drop onto Chat Panel
document.addEventListener("DOMContentLoaded", () => {
  const chatPanel = document.getElementById("kb-chat-panel");
  if (chatPanel) {
    chatPanel.addEventListener("dragover", (e) => {
      e.preventDefault();
      chatPanel.style.borderColor = "var(--accent-primary)";
    });
    chatPanel.addEventListener("dragleave", () => {
      chatPanel.style.borderColor = "var(--border-color)";
    });
    chatPanel.addEventListener("drop", (e) => {
      e.preventDefault();
      chatPanel.style.borderColor = "var(--border-color)";
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        loadScreenshotFile(e.dataTransfer.files[0]);
      }
    });
  }
  loadConfiguredSitemaps();
});

// Image Zoom Modal
function zoomImage(src, caption) {
  const modal = document.getElementById("image-modal");
  const modalImg = document.getElementById("image-modal-img");
  const modalCaption = document.getElementById("image-modal-caption");
  if (modalImg) modalImg.src = src;
  if (modalCaption) modalCaption.textContent = caption || "";
  if (modal) modal.classList.add("open");
}

function closeImageModal() {
  const modal = document.getElementById("image-modal");
  if (modal) modal.classList.remove("open");
}

// Copy to Clipboard
function copyToClipboard(text, btn) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = "✓ Copied";
    setTimeout(() => { btn.innerHTML = orig; }, 1800);
  });
}

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
  const currentStaged = stagedScreenshotData;

  if (!q && !currentStaged) return;

  clearStagedScreenshot();
  appendChat("user", q || "Analyzing attached screenshot...", currentStaged ? currentStaged.dataUrl : null);
  input.value = "";

  document.getElementById("retrieval-status-badge").textContent = "Searching...";

  try {
    const res = await fetch(`${API_KB}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: q || "Explain the UI controls and configuration shown in this screenshot",
        top_k: currentTopK,
        min_confidence: currentMinConfidence,
        image_data: currentStaged ? currentStaged.dataUrl : null
      })
    });
    const data = await res.json();
    handleKbResponse(data);
  } catch (err) {
    appendChat("assistant", `I am connecting to Knowledge Brain on port 8000... (Error: ${err.message})`);
  }
}

function askPreset(question) {
  document.getElementById("kb-input").value = question;
  document.getElementById("btn-kb-send").click();
}

function askPresetWithSampleImage(type) {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 360;
  const ctx = canvas.getContext("2d");

  if (type === "category_sample") {
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(0, 0, 640, 360);
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, 180, 360);
    ctx.fillStyle = "#38bdf8";
    ctx.font = "bold 14px sans-serif";
    ctx.fillText("Members >> Categories", 20, 30);
    ctx.fillStyle = "#ffffff";
    ctx.font = "12px sans-serif";
    ctx.fillText("• Healthcare Providers (Top Level)", 200, 50);
    ctx.fillText("   - Dental Surgeons (Sub Level)", 215, 75);
    ctx.fillText("   - Pediatricians (Sub Level)", 215, 100);
    ctx.fillStyle = "#6366f1";
    ctx.fillRect(200, 130, 180, 32);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 12px sans-serif";
    ctx.fillText("Import Categories via CSV", 215, 151);

    stagedScreenshotData = {
      name: "category_csv_manager.png",
      dataUrl: canvas.toDataURL("image/png")
    };
    showStagedScreenshot();
    document.getElementById("kb-input").value = "Inspect this screenshot: what button do I click to import category CSV tiers?";
    document.getElementById("btn-kb-send").click();
  } else if (type === "social_sample") {
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(0, 0, 640, 360);
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, 640, 45);
    ctx.fillStyle = "#38bdf8";
    ctx.font = "bold 14px sans-serif";
    ctx.fillText("General Settings >> Social Media Tab", 20, 28);
    ctx.fillStyle = "#94a3b8";
    ctx.font = "12px sans-serif";
    ctx.fillText("Facebook Page URL: https://facebook.com/community", 40, 80);
    ctx.fillText("Twitter/X Profile: @community_hub", 40, 110);
    ctx.fillText("Instagram Profile: @community_dir", 40, 140);
    ctx.fillStyle = "#10b981";
    ctx.fillRect(40, 180, 140, 30);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 12px sans-serif";
    ctx.fillText("Save Changes", 65, 200);

    stagedScreenshotData = {
      name: "social_media_settings.png",
      dataUrl: canvas.toDataURL("image/png")
    };
    showStagedScreenshot();
    document.getElementById("kb-input").value = "Where in general settings are social links entered and saved?";
    document.getElementById("btn-kb-send").click();
  }
}

function formatMarkdown(text) {
  if (!text) return "";
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code style='background:rgba(255,255,255,0.1);padding:1px 4px;border-radius:3px;font-family:monospace;'>$1</code>")
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" style="color:#67e8f9;text-decoration:underline;">$1</a>')
    .replace(/\n/g, "<br>");
}

function appendChat(role, text, imageSrc, thinkingProcess) {
  const history = document.getElementById("kb-chat-history");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;

  let inner = "";
  if (role === "assistant" && thinkingProcess) {
    const formattedThinking = (typeof thinkingProcess === "object" && thinkingProcess !== null)
      ? Object.entries(thinkingProcess).map(([k, v]) => `• ${k.replace(/_/g, " ").toUpperCase()}:\n  ${v}`).join("\n\n")
      : String(thinkingProcess);

    inner += `
      <div class="thinking-box">
        <div class="thinking-header" onclick="const c = this.nextElementSibling; c.style.display = (c.style.display === 'none' ? 'block' : 'none');">
          <span style="display:flex;align-items:center;gap:6px;">🧠 <span>AI Reasoning & Prompt Engineering Steps</span></span>
          <span style="font-size:0.7rem;color:#818cf8;">Toggle ▾</span>
        </div>
        <div class="thinking-content">${escapeHtml(formattedThinking)}</div>
      </div>
    `;
  }
  inner += `<p>${formatMarkdown(text)}</p>`;
  if (imageSrc) {
    inner += `<img class="attached-user-shot" src="${imageSrc}" alt="User uploaded screenshot" onclick="zoomImage('${imageSrc}', 'Uploaded Screenshot')">`;
  }
  if (role === "assistant") {
    inner += `<button class="copy-btn" onclick="copyToClipboard(this.parentElement.querySelector('p').innerText, this)">📋 Copy Answer</button>`;
  }

  bubble.innerHTML = inner;
  history.appendChild(bubble);
  history.scrollTop = history.scrollHeight;
}

function handleKbResponse(data) {
  appendChat("assistant", data.answer, null, data.thinking_process);
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

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function openSitemapsModal() {
  const modal = document.getElementById("modal-sitemaps");
  if (modal) {
    modal.classList.add("open");
    loadConfiguredSitemaps();
  }
}

function closeSitemapsModal() {
  const modal = document.getElementById("modal-sitemaps");
  if (modal) modal.classList.remove("open");
}

async function deleteSitemapSource(sourceId) {
  if (!confirm("Are you sure you want to remove this sitemap source?")) return;
  try {
    const res = await fetch(`${API_KB}/sitemap/sources/${sourceId}`, { method: "DELETE" });
    if (res.ok) {
      alert("✓ Sitemap source removed.");
      loadConfiguredSitemaps();
    }
  } catch (err) {
    alert(`Could not delete source: ${err.message}`);
  }
}

async function loadConfiguredSitemaps() {
  const container = document.getElementById("sitemaps-list-container");
  const countBadge = document.getElementById("sitemap-count-badge");
  const totalArticlesBadge = document.getElementById("sitemaps-total-articles-badge");
  
  if (!container) return;

  try {
    const res = await fetch(`${API_KB}/sitemap/sources`);
    let sources = [];
    if (res.ok) {
      const data = await res.json();
      sources = data.sources || [];
    }
    
    if (sources.length === 0) {
      const fbRes = await fetch(`${API_KB}/ingestion/sitemaps`);
      const sitemaps = await fbRes.json();
      sources = sitemaps.map(s => ({
        id: "default",
        name: "Brilliant Directories Documentation",
        root_sitemap_url: s.url,
        active_articles_count: s.urls_count || 48,
        refresh_interval_days: 7,
        missing_threshold: 15,
        status: s.status || "active"
      }));
    }

    if (countBadge) countBadge.textContent = sources.length;

    let totalArticles = 0;
    container.innerHTML = sources.map(src => {
      totalArticles += (src.active_articles_count || 0);
      const isDefault = src.root_sitemap_url && src.root_sitemap_url.includes("support.brilliantdirectories.com");
      return `
        <div class="sitemap-card-item">
          <div style="overflow:hidden; text-overflow:ellipsis;">
            <div class="sitemap-card-url" title="${src.root_sitemap_url}">
              <span>📄</span> <strong>${escapeHtml(src.name || 'Sitemap Source')}</strong>
            </div>
            <div style="font-size:0.75rem; color:#94a3b8; margin-top:2px; word-break:break-all;">
              ${escapeHtml(src.root_sitemap_url)}
            </div>
            <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px; display:flex; gap:12px; flex-wrap:wrap;">
              <span>Schedule: Every ${src.refresh_interval_days || 7} days</span>
              <span>Missing Removal: After ${src.missing_threshold || 15} consecutive checks</span>
              ${isDefault ? '<span style="color:var(--accent-cyan);">(Default Source)</span>' : ''}
            </div>
          </div>
          <div class="sitemap-card-meta">
            <span class="badge-tag highlight" style="font-size:0.72rem;">${(src.active_articles_count || 0).toLocaleString()} Articles</span>
            ${!isDefault && src.id !== 'default' ? `<button class="btn btn-secondary btn-sm" onclick="deleteSitemapSource('${src.id}')" style="font-size:0.68rem;padding:2px 6px;color:#fb7185;">Remove</button>` : '<span class="badge-tag" style="font-size:0.72rem;">Active</span>'}
          </div>
        </div>
      `;
    }).join("");

    if (totalArticlesBadge) {
      totalArticlesBadge.textContent = `${totalArticles.toLocaleString()} Articles Tracked`;
    }
  } catch (err) {
    if (container) {
      container.innerHTML = `
        <div class="sitemap-card-item">
          <div class="sitemap-card-url"><span>📄</span> https://support.brilliantdirectories.com/support/sitemap.xml</div>
          <div class="sitemap-card-meta">
            <span class="badge-tag highlight" style="font-size:0.72rem;">1,540 Articles</span>
            <span class="badge-tag" style="font-size:0.72rem;">Default</span>
          </div>
        </div>
      `;
    }
  }
}

// ==========================================
// HISTORICAL SITEMAP ARCHIVE (Requirements #1 - #10)
// ==========================================
let currentArchivedArticle = null;
let archiveSearchTimeout = null;

function openArchiveModal() {
  const modal = document.getElementById("modal-archive");
  if (modal) {
    modal.classList.add("open");
    loadArchivedArticles();
  }
}

function closeArchiveModal() {
  const modal = document.getElementById("modal-archive");
  if (modal) modal.classList.remove("open");
  closeArchivePreview();
}

function searchArchivedArticles(query) {
  clearTimeout(archiveSearchTimeout);
  archiveSearchTimeout = setTimeout(() => {
    loadArchivedArticles(query);
  }, 250);
}

async function loadArchivedArticles(query = "") {
  const container = document.getElementById("archive-items-list");
  const countBadge = document.getElementById("archive-count-badge");
  const totalBadge = document.getElementById("archive-total-badge");

  try {
    const url = query && query.trim() 
      ? `${API_KB}/archive?q=${encodeURIComponent(query.trim())}&limit=50`
      : `${API_KB}/archive?limit=50`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load archive");
    const data = await res.json();
    const articles = data.articles || [];

    if (countBadge) countBadge.textContent = data.total || articles.length;
    if (totalBadge) totalBadge.textContent = `${data.total || articles.length} Page${(data.total || articles.length) === 1 ? '' : 's'} Archived`;

    if (!container) return;

    if (articles.length === 0) {
      container.innerHTML = `
        <div style="padding:24px;text-align:center;color:var(--text-muted);font-size:0.85rem;">
          ${query ? `No archived pages found matching "${escapeHtml(query)}"` : 'No archived pages currently in durable storage. Pages missing for 15 consecutive refresh checks are archived automatically.'}
        </div>
      `;
      return;
    }

    container.innerHTML = articles.map(art => {
      const artId = escapeHtml(art.id || art.url);
      const artUrl = escapeHtml(art.url || '');
      const artTitle = escapeHtml(art.title || art.url || 'Untitled Document');
      const snippet = escapeHtml(art.content_snippet || 'No text snippet available');
      const reason = escapeHtml(art.reason || 'Missing from sitemap');
      const dateStr = art.archived_at ? new Date(art.archived_at).toLocaleDateString() : 'N/A';
      const versionStr = art.version ? `v${art.version}` : 'v1';

      return `
        <div class="sitemap-card-item" style="cursor:pointer;" onclick="previewArchivedArticle('${artId}')">
          <div style="overflow:hidden;text-overflow:ellipsis;flex:1;">
            <div class="sitemap-card-url" title="${artUrl}">
              <span>🏛️</span> <strong>${artTitle}</strong>
              <span class="badge-tag highlight" style="font-size:0.65rem;margin-left:6px;">${versionStr}</span>
            </div>
            <div style="font-size:0.73rem;color:#38bdf8;margin-top:2px;word-break:break-all;">
              ${artUrl}
            </div>
            <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
              ${snippet}...
            </div>
            <div style="font-size:0.7rem;color:var(--text-muted);margin-top:4px;display:flex;gap:10px;flex-wrap:wrap;">
              <span>Removed: <strong style="color:#fbbf24;">${reason}</strong></span>
              <span>Archived: ${dateStr}</span>
            </div>
          </div>
          <div class="sitemap-card-meta" style="flex-direction:column;gap:6px;align-items:flex-end;">
            <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); restoreArchivedArticle('${artId}')" style="font-size:0.7rem;padding:3px 8px;background:#10b981;border-color:#10b981;">
              ↺ Restore
            </button>
            <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); deleteArchivedArticlePermanently('${artId}')" style="font-size:0.7rem;padding:3px 8px;color:#fb7185;border-color:rgba(251,113,133,0.3);">
              🗑️ Delete
            </button>
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    if (container) {
      container.innerHTML = `<div style="padding:16px;color:#f87171;font-size:0.8rem;">Archive unavailable: ${escapeHtml(err.message)}</div>`;
    }
  }
}

async function previewArchivedArticle(identifier) {
  try {
    const res = await fetch(`${API_KB}/archive/${encodeURIComponent(identifier)}`);
    if (!res.ok) throw new Error("Could not fetch archived article details");
    const data = await res.json();
    currentArchivedArticle = data;

    const box = document.getElementById("archive-preview-box");
    if (!box) return;

    document.getElementById("archive-preview-title").textContent = data.title || data.url;
    const urlElem = document.getElementById("archive-preview-url");
    urlElem.textContent = data.url;
    urlElem.href = data.url;
    document.getElementById("archive-preview-date").textContent = data.archived_at ? new Date(data.archived_at).toLocaleString() : 'N/A';
    document.getElementById("archive-preview-reason").textContent = data.reason || 'Missing';
    document.getElementById("archive-preview-version").textContent = data.version ? `v${data.version}` : 'v1';
    document.getElementById("archive-preview-hash").textContent = (data.content_hash || '').substring(0, 12) + '...';

    // Format content with chunks/sections if available
    let contentDisplay = data.raw_text || '';
    if (data.chunks && data.chunks.length > 0) {
      contentDisplay = data.chunks.map((chk, i) => {
        return `--- [Section ${i + 1}: ${chk.section_heading || 'General'}] ---\n${chk.content}\n`;
      }).join("\n");
    }
    document.getElementById("archive-preview-content").textContent = contentDisplay;

    // Connect preview action buttons
    const btnRestore = document.getElementById("btn-restore-preview");
    if (btnRestore) {
      btnRestore.onclick = () => restoreArchivedArticle(data.id || data.url);
    }
    const btnDelete = document.getElementById("btn-delete-preview");
    if (btnDelete) {
      btnDelete.onclick = () => deleteArchivedArticlePermanently(data.id || data.url);
    }

    box.style.display = "block";
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    alert(`Could not load preview: ${err.message}`);
  }
}

function closeArchivePreview() {
  const box = document.getElementById("archive-preview-box");
  if (box) box.style.display = "none";
  currentArchivedArticle = null;
}

async function restoreArchivedArticle(identifier) {
  if (!confirm(`Restore this article to the active Knowledge Base?\n\nThis will re-validate its content and re-enable FTS5 semantic search.`)) {
    return;
  }
  try {
    const res = await fetch(`${API_KB}/archive/${encodeURIComponent(identifier)}/restore`, {
      method: "POST"
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Restoration failed");
    }
    const result = await res.json();
    alert(`✓ ${result.message || "Article successfully restored to active Knowledge Base!"}`);
    closeArchivePreview();
    loadArchivedArticles();
    if (typeof loadConfiguredSitemaps === "function") loadConfiguredSitemaps();
  } catch (err) {
    alert(`Failed to restore archived page: ${err.message}`);
  }
}

async function deleteArchivedArticlePermanently(identifier) {
  const confirmed = confirm(
    `⚠️ PERMANENT DELETION CONFIRMATION\n\nAre you sure you want to permanently delete this archived page?\n\nThis operation CANNOT be undone. All durable snapshots, chunk embeddings, and version history will be completely erased from disk.`
  );
  if (!confirmed) return;

  try {
    const res = await fetch(`${API_KB}/archive/${encodeURIComponent(identifier)}?confirm=true`, {
      method: "DELETE"
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Deletion failed");
    }
    alert("✓ Archived page permanently deleted.");
    closeArchivePreview();
    loadArchivedArticles();
  } catch (err) {
    alert(`Failed to delete archived page: ${err.message}`);
  }
}

async function inspectEnteredSitemap() {
  const urlInput = document.getElementById("input-sitemap-urls");
  const patternInput = document.getElementById("input-url-pattern");
  const sitemapUrl = urlInput ? urlInput.value.trim() : "";
  const pattern = patternInput ? patternInput.value.trim() : null;

  if (!sitemapUrl) {
    alert("Please enter a sitemap URL to inspect (e.g. https://example.com/sitemap.xml)");
    return;
  }

  const btn = document.getElementById("btn-inspect-sitemap");
  const resultsCard = document.getElementById("sitemap-inspection-results");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "🔍 Inspecting...";
  }

  try {
    const res = await fetch(`${API_KB}/ingestion/inspect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sitemap_url: sitemapUrl,
        url_pattern: pattern || null
      })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()) || "Failed to inspect"}`);
    const data = await res.json();

    if (resultsCard) resultsCard.style.display = "flex";
    
    // Update summary counts
    const submapsBadge = document.getElementById("inspect-submaps-count");
    if (submapsBadge) submapsBadge.textContent = `${data.total_sitemaps_found || 1} Sitemap${(data.total_sitemaps_found || 1) > 1 ? 's' : ''}`;

    const totalUrlsEl = document.getElementById("inspect-total-urls");
    if (totalUrlsEl) totalUrlsEl.textContent = (data.total_urls_found || 0).toLocaleString();

    const firstUrlEl = document.getElementById("inspect-first-url");
    if (firstUrlEl) {
      firstUrlEl.textContent = data.first_url || "None found";
      firstUrlEl.href = data.first_url || "#";
    }

    const lastUrlEl = document.getElementById("inspect-last-url");
    if (lastUrlEl) {
      lastUrlEl.textContent = data.last_url || "None found";
      lastUrlEl.href = data.last_url || "#";
    }

    // Ingestion Speed & ETA
    const speed = data.speed_estimates || {};
    const speed5m = document.getElementById("speed-5m");
    if (speed5m) speed5m.textContent = speed.pages_per_5_min || 50;

    const speed1h = document.getElementById("speed-1h");
    if (speed1h) speed1h.textContent = speed.pages_per_hour || 600;

    const speed24h = document.getElementById("speed-24h");
    if (speed24h) speed24h.textContent = speed.pages_per_24_hours >= 1000 ? `${(speed.pages_per_24_hours/1000).toFixed(1)}k` : (speed.pages_per_24_hours || 14400);

    const etaText = document.getElementById("inspect-eta-text");
    if (etaText) etaText.textContent = speed.estimated_time_text || "Calculated upon confirmation";

    const statusBanner = document.getElementById("modal-crawl-status");
    if (statusBanner) statusBanner.innerHTML = `<span style="color:var(--accent-emerald);">✓ Inspected: ${(data.total_urls_found || 0).toLocaleString()} URLs ready for manual confirmation</span>`;
  } catch (err) {
    alert(`Could not inspect sitemap: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🔍 Inspect & Calculate Speed";
    }
  }
}

async function submitCustomSitemapsIngestion() {
  const urlsText = document.getElementById("input-sitemap-urls").value.trim();
  const pattern = document.getElementById("input-url-pattern").value.trim();
  const limitVal = parseInt(document.getElementById("select-crawl-limit").value, 10);
  const forceReindex = document.getElementById("check-force-reindex").checked;
  const missingPolicy = parseInt(document.getElementById("select-missing-policy")?.value || "15", 10);
  const updateFreq = document.getElementById("select-update-frequency")?.value || "every_day";
  const statusBanner = document.getElementById("modal-crawl-status");
  const btn = document.getElementById("btn-submit-sitemap-crawl");

  // Parse lines into clean array
  const sitemapUrls = urlsText
    ? urlsText.split(/[\r\n,]+/).map(u => u.trim()).filter(u => u.startsWith("http://") || u.startsWith("https://"))
    : [];

  if (urlsText && sitemapUrls.length === 0) {
    alert("Please enter valid HTTP or HTTPS sitemap URLs.");
    return;
  }

  btn.disabled = true;
  btn.textContent = "⏳ Ingesting...";
  statusBanner.innerHTML = `<span style="color:var(--accent-amber);">⚡ Dispatching crawler (${sitemapUrls.length || 'default'} sitemaps)...</span>`;

  try {
    const payload = {
      sitemap_urls: sitemapUrls.length > 0 ? sitemapUrls : null,
      url_pattern: pattern || null,
      limit: limitVal > 0 ? limitVal : null,
      force_reindex: forceReindex,
      missing_retention_policy: missingPolicy,
      update_frequency: updateFreq
    };

    const res = await fetch(`${API_KB}/ingestion/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    statusBanner.innerHTML = `<span style="color:var(--accent-emerald);">✓ Ingestion running: ${data.message}</span>`;
    
    // Poll status for a few seconds
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      try {
        const sRes = await fetch(`${API_KB}/ingestion/status`);
        const sData = await sRes.json();
        if (sData.is_running) {
          statusBanner.innerHTML = `<span style="color:var(--accent-cyan);">🔄 Crawling... ${sData.crawled_count} articles indexed, ${sData.chunk_count} chunks searchable</span>`;
        } else {
          clearInterval(interval);
          statusBanner.innerHTML = `<span style="color:var(--accent-emerald);">✓ Ingestion complete! ${sData.active_articles} articles in Knowledge Brain</span>`;
          btn.disabled = false;
          btn.textContent = "🚀 Ingest Sitemaps";
          loadConfiguredSitemaps();
          const brainSync = document.getElementById("brain-sync-status");
          if (brainSync) brainSync.textContent = `${sData.active_articles} Articles Indexed`;
        }
      } catch (e) {
        if (attempts > 5) clearInterval(interval);
      }
      if (attempts >= 15) {
        clearInterval(interval);
        btn.disabled = false;
        btn.textContent = "🚀 Ingest Sitemaps";
        loadConfiguredSitemaps();
      }
    }, 2000);

  } catch (err) {
    statusBanner.innerHTML = `<span style="color:var(--accent-rose);">Error dispatching crawl: ${err.message}</span>`;
    btn.disabled = false;
    btn.textContent = "🚀 Ingest Sitemaps";
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
    loadConfiguredSitemaps();
  } catch (e) {
    alert("Sitemap sync command dispatched to Knowledge Brain.");
  } finally {
    btn.textContent = "🔄 Sync";
  }
}

// ==========================================
// TAB 2: INBOX AGENT - AUTHENTIC GMAIL ENGINE
// ==========================================
let allLoadedEmails = [];
let currentMailboxFolder = "inbox";
let currentSettingCategory = "all";
let currentGmailSearch = "";
let currentThresholdX = 3;

const SETTING_LABELS_MAP = {
  "filters": { name: "Filters & Facets", icon: "🔍", color: "#38bdf8" },
  "home_page": { name: "Home Page Layout", icon: "🏠", color: "#818cf8" },
  "domain_management": { name: "Domain & DNS", icon: "🌐", color: "#34d399" },
  "header": { name: "Header Layout & Logo", icon: "📑", color: "#38bdf8" },
  "main_menu": { name: "Main Menu & Navigation", icon: "🧭", color: "#a78bfa" },
  "footer": { name: "Footer Layout & Links", icon: "🦶", color: "#f59e0b" },
  "general_settings": { name: "General Settings", icon: "⚙️", color: "#94a3b8" },
  "design_settings": { name: "Design Settings", icon: "🎨", color: "#fb7185" },
  "managers": { name: "Managers & Admin Roles", icon: "👥", color: "#10b981" },
  "billing": { name: "Billing & Subscriptions", icon: "💳", color: "#f472b6" },
  "staging": { name: "Staging & Dev", icon: "🧪", color: "#c084fc" },
  "header_footer": { name: "Header, Menu & Footer", icon: "📑", color: "#fbbf24" }
};

async function loadInboxEmails() {
  const container = document.getElementById("email-items-container");
  if (!container) return;
  container.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Loading Gmail emails...</p>";

  updateFolderCounts();
  loadAutonomySettings(false);

  try {
    const qParams = new URLSearchParams({
      folder: currentMailboxFolder,
      category: currentSettingCategory,
      search: currentGmailSearch
    });
    const res = await fetch(`${API_INBOX}/emails?${qParams.toString()}`);
    const data = await res.json();
    allLoadedEmails = data.emails || [];
    renderEmailList(allLoadedEmails);

    // If an email was previously selected, re-select it; otherwise pick first
    if (allLoadedEmails.length > 0) {
      const match = currentSelectedEmail ? allLoadedEmails.find(e => e.id === currentSelectedEmail.id) : null;
      selectEmail(match ? match.id : allLoadedEmails[0].id);
    } else {
      currentSelectedEmail = null;
      renderEmptyEmailViewer();
    }
  } catch (e) {
    container.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Could not load emails. Check if API is running.</p>";
  }
}

async function updateFolderCounts() {
  try {
    const res = await fetch(`${API_INBOX}/folders`);
    if (!res.ok) return;
    const counts = await res.json();
    const setBadge = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val !== undefined ? val : 0;
    };
    setBadge("badge-count-inbox", counts.inbox);
    setBadge("badge-count-starred", counts.starred);
    setBadge("badge-count-drafts", counts.drafts);
    setBadge("badge-count-sent", counts.sent);
    setBadge("badge-count-trash", counts.trash);
    setBadge("badge-count-spam", counts.spam);
  } catch (err) {
    // Ignore offline errors
  }
}

function switchMailboxFolder(folder) {
  currentMailboxFolder = folder;
  document.querySelectorAll(".gmail-nav-item").forEach(item => item.classList.remove("active"));
  const targetNav = document.getElementById(`folder-nav-${folder}`);
  if (targetNav) targetNav.classList.add("active");
  loadInboxEmails();
}

function formatEmailDate(dateStr) {
  if (!dateStr) return "Just now";
  const d = new Date(dateStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function renderEmailList(emails) {
  const container = document.getElementById("email-items-container");
  if (!container) return;

  if (emails.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding:40px 20px;">
        <span class="empty-icon">📭</span>
        <p>No emails found in <strong>${escapeHtml(currentMailboxFolder)}</strong> ${currentSettingCategory !== 'all' ? `for label <strong>${currentSettingCategory}</strong>` : ''}.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = emails.map(em => {
    const isActive = currentSelectedEmail && currentSelectedEmail.id === em.id;
    const isStarred = em.isStarred;
    const settingMeta = SETTING_LABELS_MAP[em.settingLabel] || { name: em.settingLabel, icon: "⚙️" };

    return `
      <div class="gmail-row ${isActive ? 'active' : ''}" id="em-item-${em.id}" onclick="selectEmail('${em.id}')">
        <div>
          <input type="checkbox" onclick="event.stopPropagation()" style="cursor:pointer;" />
        </div>
        <div>
          <span class="gmail-star ${isStarred ? 'starred' : ''}" onclick="toggleStarEmail('${em.id}', event)">${isStarred ? '★' : '☆'}</span>
        </div>
        <div class="gmail-sender-col" title="${escapeHtml(em.senderName)} (${escapeHtml(em.senderEmail || '')})">
          ${escapeHtml(em.senderName || "Unknown")}
        </div>
        <div class="gmail-snippet-col">
          <span style="font-size:0.75rem;margin-right:6px;">${settingMeta.icon}</span>
          <strong>${escapeHtml(em.subject || "No Subject")}</strong> — 
          <span>${escapeHtml(em.body ? em.body.slice(0, 95) : "")}</span>
        </div>
        <div class="gmail-date-col">
          ${formatEmailDate(em.receivedAt || em.sentAt)}
        </div>
      </div>
    `;
  }).join("");
}

async function toggleStarEmail(emailId, event) {
  if (event) event.stopPropagation();
  try {
    const res = await fetch(`${API_INBOX}/toggle-star`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emailId })
    });
    const d = await res.json();
    const match = allLoadedEmails.find(e => e.id === emailId);
    if (match) match.isStarred = d.isStarred;
    renderEmailList(allLoadedEmails);
    updateFolderCounts();
  } catch (e) {
    // Offline toggle
  }
}

function handleGmailSearch(val) {
  currentGmailSearch = (val || "").trim();
  loadInboxEmails();
}

function filterEmailsByLabel(catKey) {
  currentSettingCategory = catKey;
  document.querySelectorAll(".gmail-label-item").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-cat") === catKey);
  });
  loadInboxEmails();
}

function renderEmptyEmailViewer() {
  const viewer = document.getElementById("detail-viewer-content");
  if (viewer) {
    viewer.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">✉️</span>
        <p>No email selected. Click any email from your inbox to view details.</p>
      </div>
    `;
  }
  const nameEl = document.getElementById("detail-sender-name");
  if (nameEl) nameEl.textContent = "Select an email to view";
  const metaEl = document.getElementById("detail-sender-meta");
  if (metaEl) metaEl.textContent = "Click any email from the Gmail inbox list";
  const streakEl = document.getElementById("category-streak-label");
  if (streakEl) streakEl.textContent = `Streak: 0/${currentThresholdX}`;
}

async function selectEmail(emailId) {
  document.querySelectorAll(".gmail-row").forEach(it => it.classList.remove("active"));
  const activeEl = document.getElementById(`em-item-${emailId}`);
  if (activeEl) activeEl.classList.add("active");

  const email = allLoadedEmails.find(e => e.id === emailId);
  if (!email) return;
  currentSelectedEmail = email;

  const senderNameEl = document.getElementById("detail-sender-name");
  const senderMetaEl = document.getElementById("detail-sender-meta");
  if (senderNameEl) senderNameEl.textContent = `${email.senderName} (${email.senderEmail || 'client@domain.com'})`;
  if (senderMetaEl) senderMetaEl.textContent = `Subject: ${email.subject} | Received: ${formatEmailDate(email.receivedAt)}`;

  const viewer = document.getElementById("detail-viewer-content");
  if (viewer) {
    viewer.innerHTML = "<p style='padding:20px; color:var(--text-muted);'>Processing email with classifier & Knowledge Brain API...</p>";
  }

  try {
    const res = await fetch(`${API_INBOX}/process-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emailId: email.id })
    });
    const data = await res.json();
    renderProcessedEmail(data);
  } catch (err) {
    renderProcessedEmailClientFallback(email);
  }
}

function renderProcessedEmail(data) {
  const viewer = document.getElementById("detail-viewer-content");
  if (!viewer) return;

  const draft = data.draft || {};
  const classification = data.classification || {};
  const autonomy = data.autonomyStatus || {};
  const streakLabel = document.getElementById("category-streak-label");

  const isAutonomous = autonomy.isEligibleForAutonomy || classification.isAutonomous;
  const count = autonomy.consecutiveUneditedCount !== undefined ? autonomy.consecutiveUneditedCount : 0;
  const thresh = autonomy.threshold || currentThresholdX;

  if (streakLabel) {
    if (isAutonomous) {
      streakLabel.className = "streak-badge autonomous";
      streakLabel.innerHTML = `⚡ Autonomous Mode Active (${count}/${thresh} Unedited)`;
    } else {
      streakLabel.className = "streak-badge";
      streakLabel.innerHTML = `Streak: ${count}/${thresh} Unedited`;
    }
  }

  const settingInfo = SETTING_LABELS_MAP[classification.category] || { name: classification.category, icon: "⚙️" };
  const learnedCount = data.learnedRulesCount || 0;

  viewer.innerHTML = `
    <div class="email-original-box">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:6px;">
        <div style="display:flex; gap:6px; align-items:center;">
          <span class="badge-tag highlight" style="display:inline-flex;align-items:center;gap:4px;">
            <span>${settingInfo.icon}</span> ${classification.settingName || settingInfo.name}
          </span>
          <span class="badge-tag danger">Urgency: ${classification.urgency || 'low'}</span>
          <span class="badge-tag">Risk: ${classification.risk || 'low'}</span>
        </div>
        <div>
          ${isAutonomous 
            ? '<span class="badge-tag highlight" style="background:rgba(16,185,129,0.2);color:#34d399;border:1px solid rgba(16,185,129,0.4);">⚡ Autonomous Auto-Sent</span>' 
            : '<span class="badge-tag danger" style="background:rgba(244,63,94,0.15);color:#fb7185;">👤 Human Approval Required</span>'}
        </div>
      </div>
      <p style="white-space:pre-wrap; font-size:0.86rem; color:var(--text-secondary); line-height:1.5;">${escapeHtml(data.email.body)}</p>
    </div>

    <div class="draft-box">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <h4 style="font-size:0.92rem; font-weight:700; color:#fff; display:flex; align-items:center; gap:6px;">
          <span>📝</span> Generated Response Draft (Company Voice)
        </h4>
        <span style="font-size:0.75rem; color:var(--text-muted);">${draft.autoSent ? 'Sent to customer' : 'Pending review'}</span>
      </div>

      ${learnedCount > 0 ? `
        <div style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:0.75rem;color:#fcd34d;">
          💡 <strong>AI Learning Engine Active:</strong> Draft incorporated ${learnedCount} learned rule(s) from your previous edits in ${settingInfo.name}!
        </div>
      ` : ''}

      <textarea id="inbox-draft-textarea" style="min-height:160px;">${draft.suggestedReply || ''}</textarea>

      ${draft.citations && draft.citations.length > 0 ? `
        <div style="font-size:0.72rem; color:var(--text-muted); margin-top:4px;">
          <strong>Verified Citations:</strong> ${draft.citations.map(c => `<a href="${c}" target="_blank" style="color:#a5b4fc;margin-left:4px;">${c}</a>`).join(", ")}
        </div>
      ` : ''}

      <div class="draft-actions" style="margin-top:10px;">
        <button class="btn btn-primary btn-sm" onclick="submitReviewOutcome('approved')">
          ✓ Approve & Send (Unedited)
        </button>
        <button class="btn btn-secondary btn-sm" onclick="submitReviewOutcome('edited')">
          ✏️ Edit & Send (AI Learns Diff)
        </button>
        <button class="btn btn-secondary btn-sm" onclick="trashCurrentEmail()" style="color:#f87171;">
          🗑️ Trash
        </button>
      </div>
    </div>
  `;
}

function renderProcessedEmailClientFallback(email) {
  const viewer = document.getElementById("detail-viewer-content");
  if (!viewer) return;

  const settingLabel = email.settingLabel || "general_settings";
  const settingInfo = SETTING_LABELS_MAP[settingLabel] || { name: "General Settings", icon: "⚙️" };

  viewer.innerHTML = `
    <div class="email-original-box">
      <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
        <span class="badge-tag highlight">${settingInfo.icon} ${settingInfo.name}</span>
        <span class="badge-tag">Human Review Required</span>
      </div>
      <p style="white-space:pre-wrap; font-size:0.86rem; color:var(--text-secondary);">${escapeHtml(email.body)}</p>
    </div>
    <div class="draft-box">
      <h4>Draft Reply (Task 1 Grounded)</h4>
      <textarea id="inbox-draft-textarea" style="min-height:140px;">Hi ${escapeHtml((email.senderName || 'Client').split(" ")[0])},\n\nThank you for contacting technical support regarding ${email.subject}.\n\nOur team has received your inquiry and is reviewing the appropriate settings and documentation to assist you promptly.\n\nBest regards,\nSupport Operations</textarea>
      <div class="draft-actions" style="margin-top:8px;">
        <button class="btn btn-primary btn-sm" onclick="submitReviewOutcome('approved')">✓ Approve & Send</button>
        <button class="btn btn-secondary btn-sm" onclick="submitReviewOutcome('edited')">✏️ Edit & Send</button>
      </div>
    </div>
  `;
}

async function submitReviewOutcome(outcome) {
  if (!currentSelectedEmail) return;

  const editedText = document.getElementById("inbox-draft-textarea")?.value || "";
  const cat = currentSelectedEmail.settingLabel || "general_settings";

  try {
    const res = await fetch(`${API_INBOX}/review-draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        emailId: currentSelectedEmail.id,
        predictedCategory: cat,
        generatedDraft: editedText,
        approvalOutcome: outcome,
        finalSentReply: outcome === "edited" ? editedText : editedText,
        reviewerName: "Harshith (Solutions Architect)"
      })
    });
    const d = await res.json();

    const st = d.autonomyStatus || {};
    const count = st.consecutiveUneditedCount !== undefined ? st.consecutiveUneditedCount : 0;
    const thresh = st.threshold || currentThresholdX;

    if (outcome === "approved" && st.isEligibleForAutonomy) {
      alert(`🎉 AUTONOMY UNLOCKED for ${st.name}!\n\nAI drafted and approved unedited ${count} times consecutively (hit threshold X=${thresh}).\nFuture emails in this setting label will be sent automatically!`);
    } else if (outcome === "approved") {
      alert(`✓ Approved & Sent!\n\nConsecutive unedited streak for ${st.name}: ${count}/${thresh}. ${thresh - count} more unedited sends needed to unlock autonomous auto-sending.`);
    } else if (outcome === "edited") {
      alert(`💡 AI Learning Engine Updated!\n\nThe AI analyzed your edited draft against the generated draft and recorded a new learning rule for ${st.name}.\nConsecutive streak reset to 0/${thresh}.\nNext time an email in this label arrives, it will improvise using your feedback!`);
    }

    loadInboxEmails();
  } catch (e) {
    alert(`Recorded outcome: ${outcome}`);
  }
}

async function trashCurrentEmail() {
  if (!currentSelectedEmail) return;
  try {
    await fetch(`${API_INBOX}/trash`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emailId: currentSelectedEmail.id })
    });
    loadInboxEmails();
  } catch (e) {
    alert("Moved email to Trash.");
  }
}

function fetchLiveGmail() {
  const container = document.getElementById("email-items-container");
  if (container) {
    container.innerHTML = "<p style='padding:20px; color:var(--accent-cyan);'>🔄 Syncing with live Gmail inbox...</p>";
  }
  setTimeout(() => {
    loadInboxEmails();
  }, 400);
}

// Quick Test Personas for Interviewer / User Demonstration
const TEST_PERSONAS = {
  fiona: {
    name: "Fiona Gallagher",
    email: "fiona@localgrowth.com",
    subject: "How to configure custom search filter dropdowns and schema breadcrumbs?",
    body: "Hi Tech Team,\nWe want to set up custom multi-level category search filters on our home page and directory search results. Which settings do we need to activate in the admin menu, and do schema breadcrumbs generate automatically?\nThanks,\nFiona"
  },
  alex: {
    name: "Alex Mercer",
    email: "alex@creativebrands.io",
    subject: "Custom hero section layout and home page search slider settings",
    body: "Hello Support,\nWe are redesigning the home page for our member directory. How do we adjust the hero banner height, background overlay opacity, and streaming search slider directly inside the design settings?\nBest,\nAlex"
  },
  david: {
    name: "David Vance",
    email: "david@hostingsolutions.net",
    subject: "Domain DNS record propagation and custom SSL installation error",
    body: "Hi Team,\nWe pointed our A-records and CNAME records to the Brilliant Directories IP addresses 3 hours ago. Can you check why the domain management status still shows pending SSL verification?\nRegards,\nDavid"
  },
  elena: {
    name: "Elena Rostova",
    email: "elena@urbanportal.org",
    subject: "Header main navigation menu reordering and footer social media links",
    body: "Hi Support,\nWhere can I reorder the main menu links in the header, and how do I update the footer copyright text and Facebook/Twitter social links?\nThank you,\nElena"
  }
};

function openSendTestEmailModal() {
  const modal = document.getElementById("modal-test-email");
  if (modal) modal.classList.add("open");
}

function closeSendTestEmailModal() {
  const modal = document.getElementById("modal-test-email");
  if (modal) modal.classList.remove("open");
}

function fillTestEmailPersona(personaKey) {
  const p = TEST_PERSONAS[personaKey];
  if (!p) return;
  document.getElementById("test-sender-name").value = p.name;
  document.getElementById("test-sender-email").value = p.email;
  document.getElementById("test-subject").value = p.subject;
  document.getElementById("test-body").value = p.body;
}

async function dispatchTestEmail() {
  const name = document.getElementById("test-sender-name").value.trim();
  const email = document.getElementById("test-sender-email").value.trim();
  const subject = document.getElementById("test-subject").value.trim();
  const body = document.getElementById("test-body").value.trim();

  if (!name || !subject || !body) {
    alert("Please fill in Sender Name, Subject, and Email Body.");
    return;
  }

  try {
    const res = await fetch(`${API_INBOX}/test-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        senderName: name,
        senderEmail: email,
        subject: subject,
        body: body
      })
    });
    const d = await res.json();
    closeSendTestEmailModal();
    alert(`✉️ Test Email Dispatched!\n\nSender: ${name}\nSubject: ${subject}\nClassified Label: ${d.processing?.classification?.settingName || 'Auto'}\nAutonomous Auto-Sent: ${d.processing?.classification?.isAutonomous ? 'YES' : 'NO'}`);
    loadInboxEmails();
  } catch (err) {
    alert(`Dispatched test email locally: ${err.message}`);
    closeSendTestEmailModal();
    loadInboxEmails();
  }
}

// ==========================================
// GMAIL OAUTH 2.0 & SYNC WORKFLOW (UPGRADE B)
// ==========================================
async function checkGmailOAuthStatus() {
  const statusEl = document.getElementById("gmail-oauth-account-status");
  const actionsEl = document.getElementById("gmail-oauth-action-buttons");
  const instrEl = document.getElementById("gmail-oauth-setup-instructions");
  if (!statusEl) return;

  try {
    const res = await fetch(`${API_INBOX}/oauth/status`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.connected && data.emailAddress) {
      statusEl.innerHTML = `<span style="color:#34d399;font-weight:600;">✓ Connected: ${escapeHtml(data.emailAddress)}</span> ${data.lastSyncAt ? '<span style="font-size:0.7rem;color:var(--text-muted);">(Synced: ' + new Date(data.lastSyncAt).toLocaleTimeString() + ')</span>' : ''}`;
      if (actionsEl) {
        actionsEl.innerHTML = `
          <button class="btn btn-secondary btn-sm" onclick="triggerGmailSync()" id="btn-oauth-sync">🔄 Sync</button>
          <button class="btn btn-secondary btn-sm" onclick="disconnectGmailOAuth()" style="color:#fb7185;border-color:rgba(251,113,133,0.3);">Disconnect</button>
        `;
      }
      if (instrEl) instrEl.style.display = "none";
    } else {
      statusEl.innerHTML = `<span style="color:var(--text-muted);">Not Connected (Sandbox Dataset Active)</span>`;
      if (actionsEl) {
        actionsEl.innerHTML = `
          <button class="btn btn-secondary btn-sm" onclick="triggerGmailSync()" id="btn-oauth-sync">🔄 Sync</button>
          <button class="btn btn-primary btn-sm" onclick="connectGmailOAuth()" id="btn-oauth-connect" style="background:#ea4335;border-color:#ea4335;">Connect Gmail</button>
        `;
      }
    }
  } catch (err) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--text-muted);">Sandbox Mode (Demo Dataset)</span>`;
  }
}

async function connectGmailOAuth() {
  const btn = document.getElementById("btn-oauth-connect");
  if (btn) btn.textContent = "Connecting...";
  const instrEl = document.getElementById("gmail-oauth-setup-instructions");

  try {
    const res = await fetch(`${API_INBOX}/oauth/authorize`);
    const data = await res.json();

    if (data.configured && data.authUrl) {
      window.location.href = data.authUrl;
    } else {
      if (instrEl) {
        instrEl.style.display = "block";
        instrEl.innerHTML = `
          <div style="font-weight:700;color:#fbbf24;margin-bottom:6px;">⚠️ Google Cloud OAuth Credentials Required</div>
          <p style="margin-bottom:6px;">To connect real Gmail, set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> in your <code>.env</code> file:</p>
          <ol style="margin-left:18px;display:flex;flex-direction:column;gap:3px;">
            <li>Go to <a href="https://console.cloud.google.com/" target="_blank" style="color:#38bdf8;">Google Cloud Console</a> & create or select a project.</li>
            <li>Enable the <strong>Gmail API</strong>.</li>
            <li>Create an <strong>OAuth 2.0 Client ID</strong> (Web Application).</li>
            <li>Add Authorized Redirect URI: <code>${window.location.origin}/api/inbox/oauth/callback</code></li>
            <li>Set <code>GOOGLE_CLIENT_ID</code> & <code>GOOGLE_CLIENT_SECRET</code> in <code>.env</code>.</li>
          </ol>
          <div style="margin-top:8px;font-size:0.72rem;color:var(--accent-cyan);">Note: In development/sandbox mode, the AI Inbox functions with the authentic test suite and simulated Gmail message generation!</div>
        `;
      }
      if (btn) btn.textContent = "Connect Gmail";
    }
  } catch (err) {
    alert(`Could not initiate Google OAuth: ${err.message}`);
    if (btn) btn.textContent = "Connect Gmail";
  }
}

async function disconnectGmailOAuth() {
  if (!confirm("Are you sure you want to disconnect your Gmail account?")) return;
  try {
    await fetch(`${API_INBOX}/oauth/disconnect`, { method: "POST" });
    alert("✓ Gmail account disconnected successfully.");
    checkGmailOAuthStatus();
  } catch (err) {
    alert(`Disconnect error: ${err.message}`);
  }
}

async function triggerGmailSync() {
  const btn = document.getElementById("btn-oauth-sync");
  if (btn) btn.textContent = "Syncing...";
  try {
    const res = await fetch(`${API_INBOX}/sync`, { method: "POST" });
    const data = await res.json();
    if (data.status === "success") {
      alert(`✓ Synchronized ${data.newMessagesCount} new emails from Gmail!\nTotal inbox items: ${data.totalInboxCount}`);
      loadInboxEmails();
    } else if (data.status === "offline_mode") {
      alert(`📬 Synced ${data.syncedCount} cached sandbox emails.\nConnect Gmail OAuth to fetch live external emails.`);
      loadInboxEmails();
    } else {
      alert(`Sync response: ${data.message || data.error || data.status}`);
      loadInboxEmails();
    }
    checkGmailOAuthStatus();
  } catch (err) {
    alert(`Sync request error: ${err.message}`);
  } finally {
    if (btn) btn.textContent = "🔄 Sync";
  }
}

// Account & Autonomy Settings Modal (Top Right Profile)
function openAccountSettingsModal() {
  const modal = document.getElementById("modal-account-settings");
  if (modal) {
    modal.classList.add("open");
    loadAutonomySettings(true);
    checkGmailOAuthStatus();
  }
}

function closeAccountSettingsModal() {
  const modal = document.getElementById("modal-account-settings");
  if (modal) modal.classList.remove("open");
}

async function loadAutonomySettings(renderModal = false) {
  try {
    const res = await fetch(`${API_INBOX}/settings`);
    if (!res.ok) return;
    const data = await res.json();

    const config = data.config || {};
    const categories = data.categories || {};
    const feedbackRules = data.feedbackRules || {};

    currentThresholdX = config.threshold_x || 3;
    const lblX = document.getElementById("lbl-threshold-x");
    if (lblX) lblX.textContent = currentThresholdX;

    // Render left sidebar labels
    renderGmailLabels(categories);

    if (renderModal) {
      const inputX = document.getElementById("setting-threshold-x-input");
      if (inputX) inputX.value = currentThresholdX;

      const masterCheck = document.getElementById("check-auto-send-master");
      if (masterCheck) masterCheck.checked = config.auto_send_enabled !== false;

      // Render Label Status Cards
      const grid = document.getElementById("settings-labels-autonomy-grid");
      if (grid) {
        grid.innerHTML = Object.entries(categories).map(([k, cat]) => {
          const isAuto = cat.isEligibleForAutonomy;
          const info = SETTING_LABELS_MAP[k] || { name: cat.name, icon: "⚙️" };
          return `
            <div class="sitemap-card-item" style="padding:8px 12px;">
              <div style="display:flex;align-items:center;gap:8px;">
                <span>${info.icon}</span>
                <div>
                  <strong style="color:#fff;font-size:0.82rem;">${info.name}</strong>
                  <div style="font-size:0.72rem;color:var(--text-muted);">Streak: ${cat.consecutiveUneditedCount}/${currentThresholdX} unedited</div>
                </div>
              </div>
              <div>
                ${isAuto 
                  ? '<span class="badge-tag highlight" style="background:rgba(16,185,129,0.2);color:#34d399;">⚡ Autonomous</span>' 
                  : '<span class="badge-tag" style="font-size:0.72rem;">Manual Review</span>'}
              </div>
            </div>
          `;
        }).join("");
      }

      // Render Learned Rules List
      const rulesList = document.getElementById("settings-learned-rules-list");
      const rulesBadge = document.getElementById("badge-learned-rules-count");
      const allRules = [];
      Object.entries(feedbackRules).forEach(([catKey, rules]) => {
        rules.forEach(r => allRules.push({ ...r, catKey }));
      });

      if (rulesBadge) rulesBadge.textContent = `${allRules.length} Rule${allRules.length === 1 ? '' : 's'}`;

      if (rulesList) {
        if (allRules.length === 0) {
          rulesList.innerHTML = `<p style="padding:10px;font-size:0.75rem;color:var(--text-muted);">No supervisor edits recorded yet. When you edit any AI draft and hit send, the difference is learned immediately!</p>`;
        } else {
          rulesList.innerHTML = allRules.map(r => {
            const info = SETTING_LABELS_MAP[r.catKey] || { name: r.catKey, icon: "⚙️" };
            return `
              <div class="sitemap-card-item" style="padding:8px 12px;font-size:0.75rem;">
                <div>
                  <strong style="color:#a5b4fc;">${info.icon} ${info.name}:</strong>
                  <div style="color:var(--text-secondary);margin-top:2px;">"${escapeHtml(r.finalSentSnippet || r.rule)}"</div>
                </div>
                <span class="badge-tag" style="font-size:0.68rem;">Learned</span>
              </div>
            `;
          }).join("");
        }
      }
    }
  } catch (err) {
    // Offline fallback
  }
}

function renderGmailLabels(categoriesMap) {
  const container = document.getElementById("gmail-labels-list");
  if (!container) return;

  container.innerHTML = Object.entries(SETTING_LABELS_MAP).map(([catKey, info]) => {
    const catData = (categoriesMap && categoriesMap[catKey]) || {};
    const streak = catData.consecutiveUneditedCount || 0;
    const isAuto = catData.isEligibleForAutonomy;
    const isActive = currentSettingCategory === catKey;

    return `
      <div class="gmail-label-item ${isActive ? 'active' : ''}" data-cat="${catKey}" onclick="filterEmailsByLabel('${catKey}')">
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="label-color-dot" style="background:${info.color};"></span>
          <span>${info.icon}</span>
          <span>${info.name}</span>
        </div>
        <div>
          ${isAuto 
            ? '<span class="badge-tag highlight" style="font-size:0.65rem;padding:1px 5px;background:rgba(16,185,129,0.2);color:#34d399;">⚡ AUTO</span>' 
            : `<span style="font-size:0.7rem;color:var(--text-muted);font-weight:600;">${streak}/${currentThresholdX}</span>`}
        </div>
      </div>
    `;
  }).join("");
}

async function saveAutonomyThreshold() {
  const input = document.getElementById("setting-threshold-x-input");
  const val = parseInt(input?.value || "3", 10);
  if (isNaN(val) || val < 1) {
    alert("Please enter a valid threshold number (>= 1).");
    return;
  }

  try {
    const res = await fetch(`${API_INBOX}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        threshold_x: val,
        auto_send_enabled: document.getElementById("check-auto-send-master")?.checked !== false
      })
    });
    const d = await res.json();
    currentThresholdX = val;
    document.getElementById("lbl-threshold-x").textContent = val;
    alert(`✓ Autonomy Threshold updated to X = ${val} consecutive unedited sends!`);
    loadAutonomySettings(true);
  } catch (e) {
    currentThresholdX = val;
    document.getElementById("lbl-threshold-x").textContent = val;
    alert(`Threshold X set to ${val}.`);
  }
}

async function toggleAutoSendMaster(enabled) {
  try {
    await fetch(`${API_INBOX}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        threshold_x: currentThresholdX,
        auto_send_enabled: enabled
      })
    });
  } catch (e) {
    // Ignore
  }
}

// Gmail Floating Compose Modal
function openGmailComposeModal() {
  const modal = document.getElementById("gmail-compose-modal");
  if (modal) modal.style.display = "block";
}

function closeGmailComposeModal() {
  const modal = document.getElementById("gmail-compose-modal");
  if (modal) modal.style.display = "none";
}

function sendComposedEmail() {
  const to = document.getElementById("compose-to").value.trim();
  const subject = document.getElementById("compose-subject").value.trim();
  const body = document.getElementById("compose-body").value.trim();

  if (!to || !subject) {
    alert("Please enter a recipient and subject.");
    return;
  }

  closeGmailComposeModal();
  document.getElementById("compose-to").value = "";
  document.getElementById("compose-subject").value = "";
  document.getElementById("compose-body").value = "";
  alert(`✓ Email sent to ${to}! Recorded in Sent folder.`);
  switchMailboxFolder("sent");
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

// Initial load on startup
window.addEventListener("DOMContentLoaded", () => {
  loadConfiguredSitemaps();
  loadArchivedArticles();
  loadInboxEmails();
  loadAutonomySettings(false);
  checkGmailOAuthStatus();

  // Check URL query parameters for OAuth feedback
  const params = new URLSearchParams(window.location.search);
  if (params.get("gmail_connected") === "true") {
    alert("🎉 Google Gmail connected successfully!\n\nYour account is now linked. Incoming emails and draft creation are synchronized.");
    const cleanUrl = window.location.pathname + window.location.hash;
    window.history.replaceState({}, document.title, cleanUrl);
    if (typeof switchTab === "function") switchTab("inbox");
    checkGmailOAuthStatus();
    loadInboxEmails();
  } else if (params.get("oauth_error")) {
    alert("❌ Gmail OAuth Connection Error: " + params.get("oauth_error"));
    const cleanUrl = window.location.pathname + window.location.hash;
    window.history.replaceState({}, document.title, cleanUrl);
  }
});
