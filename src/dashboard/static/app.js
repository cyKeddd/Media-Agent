let viewData = null;
let calYear = new Date().getFullYear();
let calMonth = new Date().getMonth();
let pollTimer = null;
const POLL_MS = 30000;

async function loadView() {
  document.getElementById('status').textContent = 'Loading…';
  const resp = await fetch('/api/view');
  viewData = await resp.json();
  renderHealth();
  renderReviewQueue();
  renderCalendar();
  renderAlerts();
  renderUploaded();
  document.getElementById('status').textContent =
    'Updated ' + new Date().toLocaleTimeString();
}

function renderHealth() {
  const h = viewData.health;
  const overall = h.overall_status;
  const gen = h.generation_run;
  const daily = h.daily_run;
  const genClass = gen.error ? ' run-failed' : '';
  const dailyClass = daily.error ? ' run-failed' : '';
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
