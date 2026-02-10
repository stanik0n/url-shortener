from fastapi.responses import HTMLResponse

UI_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>URL Shortener</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      margin: 40px auto;
      max-width: 1000px;
      background: #fafafa;
    }
    h1 { margin-bottom: 8px; }
    .small { font-size: 13px; color: #555; }
    .card {
      background: #fff;
      padding: 20px;
      border-radius: 10px;
      box-shadow: 0 6px 20px rgba(0,0,0,0.06);
      margin-bottom: 24px;
    }
    input, button {
      padding: 10px;
      font-size: 14px;
    }
    input { width: 100%; margin-bottom: 10px; }
    button { cursor: pointer; }
    .row { display: flex; gap: 12px; align-items: center; }
    .row input { flex: 1; margin-bottom: 0; }
    .success {
      background: #f0fff4;
      border-left: 4px solid #22c55e;
      padding: 12px;
      margin-top: 12px;
      border-radius: 6px;
    }
    .error {
      background: #fff5f5;
      border-left: 4px solid #ef4444;
      padding: 12px;
      margin-top: 12px;
      border-radius: 6px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      background: #fff;
      border-radius: 10px;
      overflow: hidden;
    }
    th, td {
      padding: 10px;
      border-bottom: 1px solid #eee;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    th { background: #f3f4f6; font-weight: 700; }
    a { color: #2563eb; font-weight: 600; text-decoration: none; }
    code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }
    .btn {
      padding: 6px 10px;
      font-size: 12px;
      border: 1px solid #ddd;
      border-radius: 8px;
      background: #fff;
    }
    .btn:hover { background: #f3f4f6; }
    .muted { color: #666; font-size: 12px; }
  </style>
</head>
<body>

<h1>🔗 URL Shortener</h1>
<p class="small">FastAPI · Redis · PostgreSQL · Async Analytics (Worker Flush)</p>

<div class="card">
  <h2>Shorten URL</h2>

  <input id="longUrl" placeholder="https://example.com/very/long/url" />
  <input id="alias" placeholder="Optional custom alias (e.g. youtube)" />

  <button onclick="shorten()">Shorten</button>

  <div id="shortenResult"></div>
</div>

<div class="card">
  <div class="row" style="justify-content: space-between;">
    <h2 style="margin: 0;">History (Multiple URLs)</h2>
    <div>
      <button class="btn" onclick="refreshAll()">Refresh now</button>
      <button class="btn" onclick="clearAll()">Clear all</button>
    </div>
  </div>
  <div class="muted">Auto-refreshes every 2 seconds.</div>

  <div id="history"></div>
</div>

<script>
const STORAGE_KEY = "url_shortener_history_v1";
let refreshTimer = null;

// Each item: { code, short_url, long_url, created_at, expires_at, click_count, last_accessed_at }
function loadItems() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveItems(items) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

let items = loadItems();

function formatTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts; // fallback if not parseable
  return d.toLocaleString();
}

function render() {
  const container = document.getElementById("history");
  if (!items.length) {
    container.innerHTML = '<div class="muted" style="margin-top:12px;">No URLs yet. Create one above.</div>';
    return;
  }

  const rows = items.map(it => `
    <tr>
      <td><code>${it.code}</code></td>
      <td>
        <a href="${it.short_url}" target="_blank">${it.short_url}</a>
        <div class="muted">Expires: ${formatTime(it.expires_at)}</div>
      </td>
      <td style="word-break: break-all;">
        <a href="${it.long_url}" target="_blank">${it.long_url}</a>
      </td>
      <td><strong>${it.click_count ?? "-"}</strong></td>
      <td>${formatTime(it.last_accessed_at)}</td>
      <td>
        <button class="btn" onclick="copyLink('${it.short_url.replace(/'/g, "\\'")}')">Copy</button>
        <button class="btn" onclick="removeItem('${it.code.replace(/'/g, "\\'")}')">Remove</button>
      </td>
    </tr>
  `).join("");

  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Code</th>
          <th>Short URL</th>
          <th>Long URL</th>
          <th>Clicks</th>
          <th>Last Accessed</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function upsertItem(newItem) {
  const idx = items.findIndex(x => x.code === newItem.code);
  if (idx >= 0) items[idx] = { ...items[idx], ...newItem };
  else items.unshift(newItem); // add newest on top
  saveItems(items);
  render();
}

function removeItem(code) {
  items = items.filter(x => x.code !== code);
  saveItems(items);
  render();
}

function clearAll() {
  if (!confirm("Clear all saved short URLs from this browser?")) return;
  items = [];
  saveItems(items);
  render();
}

async function copyLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    alert("Copied to clipboard!");
  } catch {
    alert("Copy failed (browser permission). URL: " + url);
  }
}

async function shorten() {
  const long_url = document.getElementById("longUrl").value.trim();
  const custom_alias = document.getElementById("alias").value.trim();
  const out = document.getElementById("shortenResult");
  out.innerHTML = "";

  if (!long_url) {
    out.innerHTML = '<div class="error">Please enter a URL</div>';
    return;
  }

  const body = { long_url };
  if (custom_alias) body.custom_alias = custom_alias;

  const res = await fetch("/shorten", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  let data;
  try { data = await res.json(); }
  catch { data = { detail: "Invalid response" }; }

  if (!res.ok) {
    out.innerHTML = '<div class="error"><strong>Error:</strong> ' + (data.detail || JSON.stringify(data)) + '</div>';
    return;
  }

  out.innerHTML = `
    <div class="success">
      <div><strong>Created:</strong> <a href="${data.short_url}" target="_blank">${data.short_url}</a></div>
      <div class="muted">Code: ${data.code} · Expires: ${formatTime(data.expires_at)}</div>
    </div>
  `;

  // Insert into history immediately (stats will populate on refresh)
  upsertItem({
    code: data.code,
    short_url: data.short_url,
    long_url: long_url,
    expires_at: data.expires_at,
  });

  // refresh stats right away
  await refreshAll();
}

async function fetchStats(code) {
  const res = await fetch("/stats/" + encodeURIComponent(code));
  if (!res.ok) return null;
  return await res.json();
}

async function refreshAll() {
  if (!items.length) return;

  // fetch stats for all codes in parallel
  const results = await Promise.all(items.map(async (it) => {
    const st = await fetchStats(it.code);
    return { code: it.code, stats: st };
  }));

  for (const r of results) {
    if (!r.stats) continue;
    upsertItem({
      code: r.stats.code,
      long_url: r.stats.long_url,
      created_at: r.stats.created_at,
      expires_at: r.stats.expires_at,
      click_count: r.stats.click_count,
      last_accessed_at: r.stats.last_accessed_at,
      // keep short_url already stored
    });
  }
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshAll, 2000);
}

render();
startAutoRefresh();
refreshAll();
</script>

</body>
</html>
"""

def ui_page():
    return HTMLResponse(UI_HTML)