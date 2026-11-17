/* Admin dashboard */
(() => {
  const clock = new RoundClock();
  const open = new Set();
  const detailCache = new Map();
  const tbody = $('#teamsTable tbody');
  let lastSig = '';

  const pill = $('#statusPill');

  function applyRound(round) {
    clock.update(round);
    pill.textContent = round.status;
    pill.className = `status-pill ${round.status}`;
    $('#btnStart').disabled = round.status !== 'waiting';
    $('#btnStop').disabled = round.status !== 'running';
  }

  async function loadDetail(id) {
    const r = await api(`/api/admin/team/${id}`);
    if (r.ok) detailCache.set(id, r.data.answers);
  }

  const detailRow = (id) => {
    const rows = detailCache.get(id) || [];
    const body = rows.map((a) => `
      <tr><td>${a.seq}</td><td><span class="tag diff-${esc(a.difficulty)}">${esc(a.difficulty)}</span></td><td>${a.theme.icon} ${esc(a.theme.kn)}</td><td>${esc(a.text_kn)}</td>
        <td>${a.answered ? esc(a.chosen) : '<span class="tag na">…</span>'}</td>
        <td>${esc(a.answer)}</td>
        <td><span class="tag ${!a.answered ? 'na' : a.correct ? 'ok' : 'no'}">${a.answered ? fmtSec(a.time_ms) : 'open'}</span></td>
        <td>${a.answered ? a.points : ''}</td></tr>`).join('');
    return `<tr class="detail"><td colspan="8"><table class="detail-table">
      <thead><tr><th>#</th><th>Level</th><th>Theme</th><th>Question</th><th>Chosen</th><th>Answer</th><th>Time taken</th><th>Pts</th></tr></thead>
      <tbody>${body || '<tr><td colspan="8">No answers yet</td></tr>'}</tbody></table></td></tr>`;
  };

  function renderTeams(teams) {
    tbody.innerHTML = teams.map((t) => `
      <tr class="team-row" data-id="${t.id}">
        <td>${t.rank}</td>
        <td><b>${esc(t.name)}</b>${t.members ? `<br><small class="muted">${esc(t.members)}</small>` : ''}</td>
        <td class="num"><b>${t.score}</b></td><td class="num">${t.answered}</td>
        <td class="num">${t.correct}</td><td class="num">${t.answered - t.correct}</td>
        <td class="num">${fmtSec(t.avg_ms)}</td><td class="num">${fmtSec(t.total_ms)}</td>
      </tr>${open.has(t.id) ? detailRow(t.id) : ''}`).join('')
      || '<tr><td colspan="8" class="muted">No teams registered yet.</td></tr>';
  }

  async function refresh() {
    const r = await api('/api/admin/overview');
    if (r.status === 401) { location.href = '/admin/login'; return; }
    if (!r.ok) return;
    const d = r.data;
    applyRound(d.round);
    $('#reviewLink').hidden = !d.review_available;
    $('#reviewStatus').hidden = d.review_available;
    $('#qCount').textContent = d.question_count;
    $('#tCount').textContent = d.teams.length;
    const link = $('#joinUrl');
    link.textContent = d.join_url; link.href = d.join_url;
    await Promise.all([...open].map(loadDetail));
    const sig = JSON.stringify([d.teams, [...open].map((id) => detailCache.get(id))]);
    if (sig !== lastSig) { lastSig = sig; renderTeams(d.teams); }
  }

  tbody.addEventListener('click', async (e) => {
    const row = e.target.closest('.team-row');
    if (!row) return;
    const id = Number(row.dataset.id);
    if (open.has(id)) open.delete(id); else { open.add(id); await loadDetail(id); }
    lastSig = '';
    refresh();
  });

  $('#btnStart').addEventListener('click', async () => {
    const minutes = parseFloat($('#minutes').value) || 5;
    if (!confirm(`Start the round now for ${minutes} minute(s)?`)) return;
    const r = await api('/api/admin/start', { minutes });
    if (!r.ok) alert('Could not start: round is not in the waiting state.');
    refresh();
  });
  $('#btnStop').addEventListener('click', async () => {
    if (confirm('End the round right now?')) { await api('/api/admin/stop', {}); refresh(); }
  });
  $('#btnReset').addEventListener('click', async () => {
    if (confirm('Start a new round? All answers and scores will be erased (teams are kept).')) {
      detailCache.clear(); await api('/api/admin/reset', { clear_teams: false }); refresh();
    }
  });
  $('#btnClear').addEventListener('click', async () => {
    if (confirm('Delete ALL teams and answers? This cannot be undone.')) {
      open.clear(); detailCache.clear(); await api('/api/admin/reset', { clear_teams: true }); refresh();
    }
  });

  setInterval(() => { $('#clock').textContent = fmtClock(clock.remainingMs); }, 100);
  refresh();
  setInterval(refresh, 2000);
})();
