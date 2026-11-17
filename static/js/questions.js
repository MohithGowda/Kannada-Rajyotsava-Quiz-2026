/* Admin: browse the question bank shown to participants */
(() => {
  const LETTERS = ['ಅ', 'ಆ', 'ಇ', 'ಈ'];
  let themes = [];
  let levels = [];
  let questions = [];
  const list = $('#list');
  const search = $('#search');
  const filter = $('#themeFilter');
  const levelFilter = $('#levelFilter');
  const showAnswers = $('#showAnswers');

  const themeOf = (key) => themes.find((t) => t.key === key) || { kn: key, en: key, icon: '❓' };
  const levelOf = (key) => levels.find((l) => l.key === key) || { kn: key, en: key };

  function render() {
    const term = search.value.trim().toLowerCase();
    const theme = filter.value;
    const level = levelFilter.value;
    const items = questions.filter((q) => {
      if (theme && q.theme !== theme) return false;
      if (level && q.difficulty !== level) return false;
      if (!term) return true;
      const hay = [q.text_kn, q.text_en, ...q.options.flatMap((o) => [o.kn, o.en])].join(' ').toLowerCase();
      return hay.includes(term);
    });
    $('#shown').textContent = `Showing ${items.length} of ${questions.length}`;
    list.innerHTML = items.map((q) => {
      const t = themeOf(q.theme);
      const l = levelOf(q.difficulty);
      return `
      <article class="card qa-card">
        <div class="q-meta">
          <span class="q-num">Q${q.position}</span>
          <span class="tag diff-${esc(q.difficulty)}">${esc(l.en)} · ${esc(l.kn)}</span>
          <span class="chip">${esc(t.icon)} ${esc(t.kn)} · ${esc(t.en)}</span>
        </div>
        <h2 class="q-kn qa-q">${esc(q.text_kn)}</h2>
        <p class="q-en">${esc(q.text_en)}</p>
        <ol class="qa-options">
          ${q.options.map((o, i) => `
            <li class="${showAnswers.checked && i === q.correct_idx ? 'is-correct' : ''}">
              <span class="opt-letter">${LETTERS[i]}</span>
              <span class="opt-text"><b>${esc(o.kn)}</b>${o.en ? `<small>${esc(o.en)}</small>` : ''}</span>
              ${showAnswers.checked && i === q.correct_idx ? '<span class="tag ok">✓ Correct</span>' : ''}
            </li>`).join('')}
        </ol>
      </article>`;
    }).join('') || '<p class="muted center">No questions match.</p>';
  }

  (async () => {
    const r = await api('/api/admin/questions');
    if (r.status === 401) { location.href = '/admin/login'; return; }
    if (!r.ok) return;
    themes = r.data.themes;
    levels = r.data.difficulties;
    questions = r.data.questions;
    const count = (k) => questions.filter((q) => q.theme === k).length;
    const countLevel = (k) => questions.filter((q) => q.difficulty === k).length;
    filter.innerHTML = `<option value="">All themes (${questions.length})</option>` +
      themes.map((t) => `<option value="${esc(t.key)}">${esc(t.icon)} ${esc(t.kn)} · ${esc(t.en)} (${count(t.key)})</option>`).join('');
    levelFilter.innerHTML = `<option value="">All difficulties</option>` +
      levels.map((l) => `<option value="${esc(l.key)}">${esc(l.en)} · ${esc(l.kn)} (${countLevel(l.key)})</option>`).join('');
    render();
  })();

  search.addEventListener('input', render);
  filter.addEventListener('change', render);
  levelFilter.addEventListener('change', render);
  showAnswers.addEventListener('change', render);
})();
