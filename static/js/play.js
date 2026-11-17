/* Participant quiz screen: questions only, no feedback, scores or per-question timing */
(() => {
  const LETTERS = ['ಅ', 'ಆ', 'ಇ', 'ಈ'];
  const clock = new RoundClock();
  const el = {
    waiting: $('#phase-waiting'), question: $('#phase-question'), result: $('#phase-result'),
    ring: $('#ring'), ringFg: $('#ringFg'), timeText: $('#timeText'),
    qTheme: $('#qTheme'), qNum: $('#qNum'), qKn: $('#qKn'), qEn: $('#qEn'),
    options: $('#options'), card: $('#questionCard'), teamCount: $('#teamCount'),
  };
  const CIRC = 2 * Math.PI * 44;

  let phase = null;
  let current = null;
  let locked = false;
  let endingTimer = null;

  const show = (name) => {
    phase = name;
    el.waiting.hidden = name !== 'waiting';
    el.question.hidden = name !== 'question';
    el.result.hidden = name !== 'result';
  };

  function showQuestion(q) {
    current = q;
    locked = false;
    el.qTheme.innerHTML = `${esc(q.theme.icon)} ${esc(q.theme.kn)}<span class="en">&nbsp;· ${esc(q.theme.en)}</span>`;
    el.qNum.textContent = `ಪ್ರಶ್ನೆ ${q.number}`;
    el.qKn.textContent = q.text_kn;
    el.qEn.textContent = q.text_en;
    el.card.classList.remove('swap'); void el.card.offsetWidth; el.card.classList.add('swap');
    el.options.innerHTML = q.options.map((o, i) => `
      <button class="option" data-i="${i}" type="button">
        <span class="opt-letter">${LETTERS[i]}</span>
        <span class="opt-text"><b>${esc(o.kn)}</b>${o.en ? `<small>${esc(o.en)}</small>` : ''}</span>
      </button>`).join('');
    window.scrollTo({ top: 0 });
    show('question');
  }

  function showResult() {
    if (phase === 'result') return;
    clearTimeout(endingTimer);
    show('result');
  }

  async function loadNext() {
    let r;
    try { r = await api('/api/next', {}); } catch (_) { return setTimeout(loadNext, 1000); }
    if (r.status === 401) { location.href = '/join'; return; }
    if (!r.data) return setTimeout(loadNext, 1000);
    clock.update(r.data.round);
    switch (r.data.state) {
      case 'question': showQuestion(r.data.question); break;
      case 'waiting': show('waiting'); break;
      default: showResult();            // finished, or every question answered
    }
  }

  async function choose(i) {
    if (locked || !current) return;
    locked = true;
    const buttons = [...el.options.children];
    buttons.forEach((b) => { b.disabled = true; });
    buttons[i].classList.add('selected');
    let r;
    try { r = await api('/api/answer', { question_id: current.id, choice: i }); }
    catch (_) { locked = false; buttons.forEach((b) => { b.disabled = false; }); buttons[i].classList.remove('selected'); return; }
    if (!r.ok && r.data && r.data.state === 'finished') return showResult();
    loadNext();
  }

  el.options.addEventListener('click', (e) => {
    const btn = e.target.closest('.option');
    if (btn) choose(Number(btn.dataset.i));
  });

  function tick() {
    const rem = clock.remainingMs;
    el.timeText.textContent = fmtClock(rem);
    const frac = clock.status === 'waiting' ? 1 : Math.min(1, rem / clock.duration);
    el.ringFg.style.strokeDashoffset = String(CIRC * (1 - frac));
    el.ring.classList.toggle('warn', clock.status === 'running' && rem <= 60000 && rem > 20000);
    el.ring.classList.toggle('danger', clock.status === 'running' && rem <= 20000);
    if (phase === 'question' && clock.over && !endingTimer) {
      locked = true;
      [...el.options.children].forEach((b) => { b.disabled = true; });
      endingTimer = setTimeout(showResult, 1200);
    }
  }

  async function pollStatus() {
    let r;
    try { r = await api('/api/status'); } catch (_) { return; }
    if (!r.ok) return;
    clock.update(r.data);
    el.teamCount.textContent = r.data.teams;
    const status = r.data.status;
    if (status === 'running' && (phase === 'waiting' || phase === null)) loadNext();
    else if (status === 'finished' && (phase === 'waiting' || phase === null)) showResult();
    else if (status === 'waiting' && phase !== 'waiting') {   // host started a new round
      clearTimeout(endingTimer); endingTimer = null;
      show('waiting');
    }
  }

  (async () => {
    const me = await api('/api/me');
    if (me.status === 401) { location.href = '/join'; return; }
    await pollStatus();
    if (phase === null) show('waiting');
    setInterval(pollStatus, 2000);
    setInterval(tick, 100);
  })();
})();
