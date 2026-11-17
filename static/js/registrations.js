/* Admin: live registration monitor with approve-and-start */
(() => {
  const rows = $('#rows');
  const btn = $('#btnStart');
  const pill = $('#statusPill');
  let lastSig = '';
  let status = 'waiting';
  let count = 0;

  const hints = {
    waiting: 'Registration is open. Start only after every team has registered.',
    running: 'Quiz is running. Registration is closed.',
    finished: 'Round finished. Use “New round” on the control page to reopen registration.',
  };

  const fmtTime = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  function render(d) {
    status = d.round.status;
    count = d.teams.length;
    $('#count').textContent = count;
    pill.textContent = status;
    pill.className = `status-pill ${status}`;
    $('#stateHint').textContent = hints[status];
    btn.disabled = status !== 'waiting' || count === 0;
    const link = $('#joinUrl');
    link.textContent = d.join_url; link.href = d.join_url;
    const sig = JSON.stringify(d.teams);
    if (sig === lastSig) return;
    lastSig = sig;
    rows.innerHTML = d.teams.map((t) => `
      <tr><td>${t.no}</td><td><b>${esc(t.name)}</b></td>
        <td>${t.members ? esc(t.members) : '<span class="muted">–</span>'}</td>
        <td class="num">${fmtTime(t.registered_at_ms)}</td></tr>`).join('')
      || '<tr><td colspan="4" class="muted">No teams registered yet. Waiting for participants to scan the QR code…</td></tr>';
  }

  async function refresh() {
    const r = await api('/api/admin/registrations');
    if (r.status === 401) { location.href = '/admin/login'; return; }
    if (r.ok) render(r.data);
  }

  btn.addEventListener('click', async () => {
    const minutes = parseFloat($('#minutes').value) || 5;
    if (!confirm(`${count} team(s) registered.\nApprove and start the quiz for ${minutes} minute(s)? Registration will close.`)) return;
    const r = await api('/api/admin/start', { minutes });
    if (!r.ok) alert('Could not start the quiz.');
    refresh();
  });

  refresh();
  setInterval(refresh, 1500);
})();
