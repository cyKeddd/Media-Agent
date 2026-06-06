let viewData = null;
let calYear = new Date().getFullYear();
let calMonth = new Date().getMonth();
let pollTimer = null;
let countdownTimer = null;
const POLL_MS = 30000;

async function loadView() {
  const statusEl = document.getElementById('status');
  statusEl.textContent = 'Loading…';
  try {
    const resp = await fetch('/api/view');
    if (!resp.ok) {
      statusEl.textContent = `API error ${resp.status} — check the terminal running the dashboard`;
      return;
    }
    viewData = await resp.json();
    if (!viewData.health) {
      statusEl.textContent =
        'Dashboard server is outdated. Stop the old process, then run: python -m src.dashboard';
      document.getElementById('health-band').innerHTML =
        '<div class="tile overall failed"><div class="label">Action required</div>' +
        '<div class="value">Restart server</div>' +
        '<div class="detail">Port 8765 is still running v1. Kill that window/process, start again from the project folder.</div></div>';
      return;
    }
    renderHealth();
    startCountdown();
    renderReviewQueue();
    renderCalendar();
    renderAlerts();
    renderUploaded();
    statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    statusEl.textContent = 'Failed to load: ' + (err.message || err);
    console.error(err);
  }
}

function renderHealth() {
  const h = viewData.health;
  const overall = h.overall_status;
  const gen = h.generation_run;
  const daily = h.daily_run;
  const genClass = gen.error ? ' run-failed' : '';
  const dailyClass = daily.error ? ' run-failed' : '';
  const nr = viewData.next_run || {};
  document.getElementById('health-band').innerHTML = `
    <div class="tile overall ${overall}">
      <div class="label">Pipeline health</div>
      <div class="value">${overall}</div>
    </div>
    <div class="tile${genClass}">
      <div class="label">Generation run</div>
      <div class="value">${esc(gen.label)}</div>
      <div class="detail">${esc(gen.detail || gen.started_at || '')}${gen.error ? '<br>' + esc(gen.error) : ''}</div>
    </div>
    <div class="tile${dailyClass}">
      <div class="label">Daily upload</div>
      <div class="value">${esc(daily.label)}</div>
      <div class="detail">${esc(daily.detail || daily.started_at || '')}${daily.error ? '<br>' + esc(daily.error) : ''}</div>
    </div>
    <div class="tile">
      <div class="label">Next generation</div>
      <div class="value" id="countdown-generation">—</div>
      <div class="detail">${nr.generation_at ? esc(new Date(nr.generation_at).toLocaleString()) : ''}</div>
    </div>
    <div class="tile">
      <div class="label">Next daily upload</div>
      <div class="value" id="countdown-daily">—</div>
      <div class="detail">${nr.daily_at ? esc(new Date(nr.daily_at).toLocaleString()) : ''}</div>
    </div>
    <div class="tile">
      <div class="label">OpenRouter today</div>
      <div class="value">${h.spend_today_cents}¢ / ${h.daily_cap_cents}¢</div>
    </div>
    <div class="tile">
      <div class="label">OpenRouter week</div>
      <div class="value">${h.spend_week_cents}¢</div>
    </div>
    <div class="tile">
      <div class="label">Unscripted topics</div>
      <div class="value">${h.unscripted_topics}</div>
    </div>`;
}

function renderAlerts() {
  const el = document.getElementById('alerts-rail');
  const alerts = (viewData.health && viewData.health.alerts) || [];
  if (!alerts.length) {
    el.innerHTML = '<p class="meta">No recent alerts.</p>';
    return;
  }
  el.innerHTML = alerts.map(a => `
    <div class="alert-row ${a.severity}">
      <div class="ts">${esc(a.timestamp)} · ${esc(a.kind)}</div>
      <div>${esc(a.message)}</div>
    </div>`).join('');
}

function renderReviewQueue() {
  const el = document.getElementById('review-queue');
  let html = '';
  if (!viewData.human_review) {
    html += '<div class="banner">Autonomous mode — approval disabled. Clips upload from pending/ without review.</div>';
  }
  if (!viewData.review_queue.length) {
    if (viewData.human_review) {
      html += '<p class="meta">No clips awaiting review.</p>';
    }
    el.innerHTML = html;
    return;
  }
  html += viewData.review_queue.map(item => {
    const actions = viewData.human_review ? `
      <div class="review-actions">
        <button class="btn-approve" data-clip="${item.clip_id}">Approve</button>
        <button class="danger btn-reject" data-clip="${item.clip_id}">Reject</button>
        <button class="secondary btn-reschedule" data-clip="${item.clip_id}">Reschedule</button>
        <button class="secondary btn-edit-title" data-clip="${item.clip_id}">Edit title</button>
      </div>` : '';
    return `
      <div class="review-card" id="clip-${item.clip_id}">
        ${item.video_relpath
          ? `<video controls preload="metadata" src="/api/video/${encodeURI(item.video_relpath)}"></video>`
          : '<p class="meta">No preview file found</p>'}
        <div class="title">${esc(item.title)}</div>
        <div class="meta">${esc(item.hook)}</div>
        <div class="meta">${item.content_kind}${item.shot_mix ? ' · ' + esc(item.shot_mix) : ''}</div>
        <div class="meta">Slot: ${item.publish_at_local || 'unscheduled'}</div>
        ${actions}
      </div>`;
  }).join('');
  el.innerHTML = html;
  document.querySelectorAll('.btn-approve').forEach(btn => {
    btn.addEventListener('click', () => confirmAction(btn.dataset.clip, 'approve'));
  });
  document.querySelectorAll('.btn-reject').forEach(btn => {
    btn.addEventListener('click', () => confirmAction(btn.dataset.clip, 'reject'));
  });
  document.querySelectorAll('.btn-reschedule').forEach(btn => {
    btn.addEventListener('click', () => rescheduleClip(btn.dataset.clip));
  });
  document.querySelectorAll('.btn-edit-title').forEach(btn => {
    btn.addEventListener('click', () => editTitleClip(btn.dataset.clip));
  });
}

function formatCountdown(targetIso) {
  const target = new Date(targetIso).getTime();
  const diff = Math.max(0, target - Date.now());
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  return `${h}h ${m}m ${s}s`;
}

function startCountdown() {
  if (countdownTimer) clearInterval(countdownTimer);
  const tick = () => {
    const nr = viewData && viewData.next_run;
    if (!nr) return;
    const genEl = document.getElementById('countdown-generation');
    const dailyEl = document.getElementById('countdown-daily');
    if (genEl && nr.generation_at) genEl.textContent = formatCountdown(nr.generation_at);
    if (dailyEl && nr.daily_at) dailyEl.textContent = formatCountdown(nr.daily_at);
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

async function rescheduleClip(clipId) {
  const when = window.prompt('New slot (ISO local datetime, e.g. 2026-06-08T10:00:00+08:00):');
  if (!when) return;
  const resp = await fetch(`/api/clip/${encodeURIComponent(clipId)}/reschedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true, publish_at_local: when }),
  });
  const data = await resp.json();
  if (data.ok) {
    if (data.warning) alert(data.warning);
    await loadView();
  } else {
    alert(data.message || 'Reschedule refused');
  }
}

async function editTitleClip(clipId) {
  const title = window.prompt('New YouTube title (hook):');
  if (!title) return;
  const resp = await fetch(`/api/clip/${encodeURIComponent(clipId)}/edit-title`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true, title }),
  });
  const data = await resp.json();
  if (data.ok) {
    await loadView();
  } else {
    alert(data.message || 'Edit refused');
  }
}

async function confirmAction(clipId, action) {
  const label = action === 'approve' ? 'Approve' : 'Reject';
  if (!window.confirm(`${label} clip ${clipId}? This moves the file on disk.`)) return;
  const resp = await fetch(`/api/clip/${encodeURIComponent(clipId)}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  });
  const data = await resp.json();
  if (data.ok) {
    await loadView();
  } else {
    alert(data.message || 'Action refused');
  }
}

function renderCalendar() {
  const label = document.getElementById('month-label');
  label.textContent = new Date(calYear, calMonth).toLocaleString(undefined, {
    month: 'long', year: 'numeric',
  });
  const first = new Date(calYear, calMonth, 1);
  const startPad = first.getDay();
  const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < startPad; i++) cells.push('<div class="cal-day"></div>');
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${calYear}-${String(calMonth + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const entries = (viewData.calendar_by_date[key] || []).map(e =>
      `<div class="cal-entry ${e.review_stage}" data-clip="${e.clip_id}" title="${esc(e.title)}">${e.slot_local} ${esc(e.title)}</div>`
    ).join('');
    cells.push(`<div class="cal-day"><div class="date-num">${d}</div>${entries}</div>`);
  }
  document.getElementById('calendar').innerHTML = cells.join('');
  document.querySelectorAll('.cal-entry').forEach(el => {
    el.addEventListener('click', () => {
      const id = el.dataset.clip;
      const target = document.getElementById('clip-' + id);
      if (target) target.scrollIntoView({ behavior: 'smooth' });
      else {
        const up = viewData.uploaded.find(u => u.clip_id === id);
        if (up) window.open(up.youtube_url, '_blank');
      }
    });
  });
}

function renderUploaded() {
  const el = document.getElementById('uploaded');
  if (!viewData.uploaded.length) {
    el.innerHTML = '<li class="meta">Nothing uploaded yet.</li>';
    return;
  }
  el.innerHTML = viewData.uploaded.map(u => `
    <li>
      <span>${esc(u.title)}</span>
      <span>
        <span class="${u.is_live ? 'live-tag' : 'sched-tag'}">${u.is_live ? 'Live' : 'Scheduled'}</span>
        <a href="${u.youtube_url}" target="_blank" rel="noopener">YouTube</a>
      </span>
    </li>`).join('');
}

function esc(s) {
  return String(s || '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

document.getElementById('refresh').addEventListener('click', loadView);
document.getElementById('prev-month').addEventListener('click', () => {
  calMonth--;
  if (calMonth < 0) { calMonth = 11; calYear--; }
  renderCalendar();
});
document.getElementById('next-month').addEventListener('click', () => {
  calMonth++;
  if (calMonth > 11) { calMonth = 0; calYear++; }
  renderCalendar();
});

loadView();
pollTimer = setInterval(loadView, POLL_MS);
