/**
 * app.js — 부품 매칭 스튜디오 서버판 프런트
 * 무거운 계산(SIFT·AI·배경제거)은 전부 서버 API 가 담당하고,
 * 이 스크립트는 업로드 → 진행률 폴링 → 결과 표시만 한다. (접속 PC 메모리 최소화)
 */

/* ========== 상태 ========== */
const state = {
  excelFiles: [], // File[]
  photoFiles: [], // File[]
  photos: [],     // 서버가 준 {name, thumb}
  pairs: [],      // 서버가 준 매칭 결과 + 사용자의 수정
  matchJob: null,
  exportJob: null,
  imgCol: 'D', codeCol: 'E', startRow: 4, failCol: 'A',
  threshold: 15, aiThreshold: 0.83,
};

const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };

function log(msg, type = 'info') {
  const body = $('#console-body');
  body.appendChild(el('div', 'l-' + type, msg));
  body.scrollTop = body.scrollHeight;
}
function setChip(text, cls) {
  const chip = $('#chip-server');
  chip.classList.remove('ready', 'error');
  if (cls) chip.classList.add(cls);
  chip.lastChild.textContent = ' ' + text;
}

/* ========== 서버 상태 확인 ========== */
async function checkServer() {
  try {
    const r = await fetch('api/health');
    const j = await r.json();
    setChip(j.ai ? '서버 연결됨 · AI 사용 가능' : '서버 연결됨 · SIFT 전용', 'ready');
    log('✔ 서버 연결 확인' + (j.ai ? ' (AI 서버 사용 가능)' : ' (AI 서버 없음 — SIFT 만 사용)'), 'ok');
  } catch (e) {
    setChip('서버 연결 실패', 'error');
    log('✖ 서버에 연결할 수 없습니다: ' + e.message, 'bad');
  }
}
checkServer();

/* ========== 업로드 ========== */
function addExcelFiles(files) {
  for (const f of files) {
    if (!f.name.toLowerCase().endsWith('.xlsx') || f.name.startsWith('~$')) continue;
    if (state.excelFiles.some((x) => x.name === f.name)) continue;
    state.excelFiles.push(f);
  }
  renderExcelList();
}
function renderExcelList() {
  const ul = $('#list-excel');
  ul.innerHTML = '';
  state.excelFiles.forEach((f, i) => {
    const li = el('li', null, `<span class="name">📄 ${f.name}</span>`);
    const rm = el('button', 'rm', '✕');
    rm.onclick = () => { state.excelFiles.splice(i, 1); renderExcelList(); };
    li.appendChild(rm);
    ul.appendChild(li);
  });
  updateCounts();
}
function addPhotoFiles(files) {
  const re = /\.(png|jpe?g|webp)$/i;
  for (const f of files) {
    if (!re.test(f.name)) continue;
    if (state.photoFiles.some((x) => x.name === f.name)) continue;
    state.photoFiles.push(f);
  }
  renderPhotoList();
}
function renderPhotoList() {
  const box = $('#list-photo');
  box.innerHTML = '';
  state.photoFiles.forEach((f, i) => {
    const t = el('div', 't');
    const img = el('img');
    img.src = URL.createObjectURL(f); // 표시용 (브라우저가 알아서 다운스케일)
    t.appendChild(img);
    const rm = el('button', 'rm', '✕');
    rm.onclick = () => { state.photoFiles.splice(i, 1); renderPhotoList(); };
    t.appendChild(rm);
    box.appendChild(t);
  });
  updateCounts();
}
function updateCounts() {
  $('#upload-counts').textContent = `엑셀 ${state.excelFiles.length}개 · 사진 ${state.photoFiles.length}장`;
  $('#btn-start').disabled = !(state.excelFiles.length && state.photoFiles.length);
}
function wireDrop(zoneId, inputId, handler) {
  const zone = $(zoneId), input = $(inputId);
  input.onchange = () => { handler(input.files); input.value = ''; };
  ['dragover', 'dragenter'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('drag'); }));
  zone.addEventListener('drop', (e) => handler(e.dataTransfer.files));
}
wireDrop('#dz-excel', '#in-excel', addExcelFiles);
wireDrop('#dz-photo', '#in-photo', addPhotoFiles);

/* ========== STEP 전환 ========== */
function goStep(n) {
  $('#panel-upload').classList.toggle('hidden', n !== 1);
  $('#panel-match').classList.toggle('hidden', n !== 2);
  $('#panel-export').classList.toggle('hidden', n !== 3);
  document.querySelectorAll('.step').forEach((s) => {
    const step = +s.dataset.step;
    s.classList.toggle('active', step === n);
    s.classList.toggle('done', step < n);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$('#btn-back').onclick = () => goStep(1);
$('#btn-back2').onclick = () => goStep(2);

/* ========== 매칭 실행 (서버) ========== */
$('#btn-start').onclick = async () => {
  goStep(2);
  $('#cardgrid').innerHTML = '';
  $('#threshold-label').textContent = state.threshold;
  $('#ai-threshold-label').textContent = Math.round(state.aiThreshold * 100);
  setMatchProgress(0, '서버에 파일 업로드 중…');
  log('━━━━━━━━━━ 자동 매칭 시작 (서버) ━━━━━━━━━━', 'dim');

  const fd = new FormData();
  state.excelFiles.forEach((f) => fd.append('excels', f));
  state.photoFiles.forEach((f) => fd.append('photos', f));
  fd.append('img_col', state.imgCol);
  fd.append('code_col', state.codeCol);
  fd.append('start_row', state.startRow);
  fd.append('threshold', state.threshold);
  fd.append('ai_threshold', state.aiThreshold);

  try {
    const r = await fetch('api/match', { method: 'POST', body: fd });
    const { job_id } = await r.json();
    state.matchJob = job_id;

    // 진행률 폴링
    while (true) {
      await sleep(700);
      const s = await (await fetch('api/match/' + job_id)).json();
      setMatchProgress(s.progress / 100, s.message);
      if (s.status === 'error') throw new Error(s.error);
      if (s.status === 'done') {
        state.photos = s.result.photos;
        state.pairs = s.result.pairs.map((p) => ({ ...p, excluded: !p.auto }));
        log(`✔ 매칭 완료 — 총 ${state.pairs.length}건 (${s.result.aiUsed ? 'AI+SIFT' : 'SIFT 전용'})`, 'ok');
        break;
      }
    }
    renderAllCards();
    updateMatchStats();
    updateUnmatched();
  } catch (e) {
    setMatchProgress(0, '매칭 실패: ' + e.message);
    log('✖ 매칭 실패: ' + e.message, 'bad');
  }
};

function setMatchProgress(ratio, label) {
  $('#match-bar').style.width = Math.round(ratio * 100) + '%';
  $('#match-label').textContent = label;
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ========== 카드 렌더 ========== */
function renderAllCards() {
  const grid = $('#cardgrid');
  grid.innerHTML = '';
  const rank = (p) => (p.excluded ? 2 : (p.auto ? 0 : 1));
  const ordered = state.pairs.map((p, i) => ({ p, i })).sort((a, b) => rank(a.p) - rank(b.p) || a.i - b.i);
  for (const { p } of ordered) grid.appendChild(buildCard(p));
}

function buildCard(pair) {
  const photo = pair.selectedIdx >= 0 && !pair.excluded ? state.photos[pair.selectedIdx] : null;
  const top = (pair.candidates || [])[0] || {};
  const status = pair.excluded ? '<span class="badge bad">제외</span>'
    : (pair.auto ? '<span class="badge ok">성공</span>' : '<span class="badge warn">수동 확정</span>');
  const sel = (pair.candidates || []).find((c) => c.photoIdx === pair.selectedIdx) || top;
  const aiTxt = sel.ai != null ? `AI <b>${(sel.ai * 100).toFixed(0)}%</b>` : '';
  const sTxt = sel.score != null ? `${aiTxt ? ' · ' : ''}SIFT <b>${sel.score}</b>` : '';

  const card = el('div', 'mcard' + (pair.excluded ? ' excluded' : ''));
  card.id = 'card-' + pair.id;
  card.innerHTML = `
    <div class="mcard-top">
      <span class="mcard-code">${pair.code}</span>
      <span class="mcard-meta">${pair.folder} · ${pair.sheet} · 행 ${pair.row}</span>
    </div>
    <div class="mcard-body">
      <div class="mimg"><img src="${pair.thumb}" alt=""></div>
      <div class="arrow">➜</div>
      <div class="mimg ${photo ? '' : 'empty'}">${photo ? `<img src="${photo.thumb}" loading="lazy">` : '없음'}</div>
    </div>
    <div class="mcard-foot">
      <span class="score">${aiTxt}${sTxt}</span>
      ${status}
      <button class="link-btn" data-act="pick">후보 변경</button>
    </div>`;
  card.querySelector('[data-act="pick"]').onclick = () => openCandModal(pair);
  return card;
}
function rerenderCard(pair) {
  const old = document.getElementById('card-' + pair.id);
  if (old) old.replaceWith(buildCard(pair));
}

function updateMatchStats() {
  const total = state.pairs.length;
  const inc = state.pairs.filter((p) => !p.excluded && p.selectedIdx >= 0).length;
  $('#match-stats').innerHTML = `
    <div class="stat"><b>${total}</b><span>전체</span></div>
    <div class="stat ok"><b>${inc}</b><span>확정</span></div>
    <div class="stat bad"><b>${total - inc}</b><span>제외</span></div>`;
}

/* ========== 미매칭 요약 ========== */
function unmatchedPairs() { return state.pairs.filter((p) => p.excluded || p.selectedIdx < 0); }
function updateUnmatched() {
  const list = unmatchedPairs();
  $('#unmatched-count').textContent = list.length;
  $('#unmatched-text').value = list.map((p) => [p.code, p.excel, p.sheet, p.row].join('\t')).join('\n');
}
$('#btn-copy-unmatched').onclick = async () => {
  try { await navigator.clipboard.writeText($('#unmatched-text').value); }
  catch (e) { $('#unmatched-text').select(); document.execCommand('copy'); }
  log('✔ 미매칭 코드 복사됨 (' + unmatchedPairs().length + '개)', 'ok');
};

/* ========== 후보 선택 팝업 ========== */
function openCandModal(pair) {
  $('#cand-code').textContent = pair.code;
  $('#cand-meta').textContent = `${pair.folder} · ${pair.sheet} · 행 ${pair.row}`;
  $('#cand-target-img').src = pair.thumb;
  const grid = $('#cand-grid');
  grid.innerHTML = '';

  const choose = (fn) => { fn(); rerenderCard(pair); updateMatchStats(); updateUnmatched(); renderAllCards(); closeCandModal(); };

  const none = el('div', 'candL none' + (pair.excluded || pair.selectedIdx < 0 ? ' sel' : ''));
  none.innerHTML = '<div class="candL-x">제외<br><small>매칭 없음</small></div>';
  none.onclick = () => choose(() => { pair.excluded = true; pair.selectedIdx = -1; });
  grid.appendChild(none);

  (pair.candidates || []).forEach((c) => {
    const p = state.photos[c.photoIdx];
    const cand = el('div', 'candL' + (c.photoIdx === pair.selectedIdx && !pair.excluded ? ' sel' : ''));
    const aiTxt = c.ai != null ? `AI ${(c.ai * 100).toFixed(0)}%` : '';
    cand.innerHTML = `<img src="${p.thumb}"><div class="candL-cap">${aiTxt}${aiTxt ? ' · ' : ''}SIFT ${c.score}</div><div class="candL-name">${p.name}</div>`;
    cand.onclick = () => choose(() => {
      pair.selectedIdx = c.photoIdx;
      pair.excluded = false;
      pair.auto = (c.ai != null && c.ai >= state.aiThreshold) || c.score >= state.threshold;
    });
    grid.appendChild(cand);
  });
  $('#modal-cand').classList.remove('hidden');
}
function closeCandModal() { $('#modal-cand').classList.add('hidden'); }
$('#cand-close').onclick = closeCandModal;
$('#modal-cand').onclick = (e) => { if (e.target.id === 'modal-cand') closeCandModal(); };

/* ========== 내보내기 (서버) ========== */
$('#btn-export').onclick = () => {
  goStep(3);
  $('#btn-zip').classList.add('hidden');
  $('#xlsx-links').innerHTML = '';
  $('#export-bar').style.width = '0%';
  $('#export-label').textContent = '"처리 시작"을 누르면 시작합니다.';
};

$('#btn-run-export').onclick = async () => {
  const items = state.pairs.filter((p) => !p.excluded && p.selectedIdx >= 0)
    .map((p) => ({ code: p.code, folder: p.folder, sheet: p.sheet, row: p.row, photoIdx: p.selectedIdx }));
  if (!items.length) { alert('내보낼 확정 항목이 없습니다.'); return; }
  const fails = unmatchedPairs().map((p) => ({ excel: p.excel, sheet: p.sheet, row: p.row }));

  $('#btn-run-export').disabled = true;
  log('━━━━━━━━━━ 내보내기 시작 (서버, ' + items.length + '건) ━━━━━━━━━━', 'dim');
  try {
    const r = await fetch('api/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ match_job: state.matchJob, items, fails, use_bg: $('#use-bg').checked, fail_col: state.failCol }),
    });
    const { job_id, error } = await r.json();
    if (error) throw new Error(error);
    state.exportJob = job_id;

    let xlsxCount = 0;
    while (true) {
      await sleep(800);
      const s = await (await fetch('api/export/' + job_id)).json();
      $('#export-bar').style.width = s.progress + '%';
      $('#export-label').textContent = s.message;
      if (s.status === 'error') throw new Error(s.error);
      if (s.status === 'done') { xlsxCount = s.xlsxCount; break; }
    }

    $('#btn-zip').href = 'api/export/' + job_id + '/zip';
    $('#btn-zip').classList.remove('hidden');
    const box = $('#xlsx-links');
    for (let i = 0; i < xlsxCount; i++) {
      const a = el('a', 'primary-btn', '📄 수정 엑셀 ' + (xlsxCount > 1 ? (i + 1) : '') + ' 다운로드');
      a.href = `api/export/${job_id}/xlsx/${i}`;
      a.style.marginLeft = '8px';
      box.appendChild(a);
    }
    log('✔ 내보내기 완료 — 버튼을 눌러 다운로드하세요', 'ok');
  } catch (e) {
    $('#export-label').textContent = '실패: ' + e.message;
    log('✖ 내보내기 실패: ' + e.message, 'bad');
  }
  $('#btn-run-export').disabled = false;
};

/* ========== 설정 ========== */
$('#btn-settings').onclick = () => {
  $('#cfg-imgcol').value = state.imgCol;
  $('#cfg-codecol').value = state.codeCol;
  $('#cfg-startrow').value = state.startRow;
  $('#cfg-failcol').value = state.failCol;
  $('#cfg-aithreshold').value = Math.round(state.aiThreshold * 100);
  $('#cfg-threshold').value = state.threshold;
  $('#modal-settings').classList.remove('hidden');
};
$('#btn-close-settings').onclick = () => {
  const colRe = /^[A-Za-z]{1,3}$/;
  const g = (id) => $(id).value.trim().toUpperCase();
  if (colRe.test(g('#cfg-imgcol'))) state.imgCol = g('#cfg-imgcol');
  if (colRe.test(g('#cfg-codecol'))) state.codeCol = g('#cfg-codecol');
  if (colRe.test(g('#cfg-failcol'))) state.failCol = g('#cfg-failcol');
  const sr = parseInt($('#cfg-startrow').value, 10); if (sr > 0) state.startRow = sr;
  const ai = parseInt($('#cfg-aithreshold').value, 10); if (ai > 0 && ai < 100) state.aiThreshold = ai / 100;
  const th = parseInt($('#cfg-threshold').value, 10); if (th > 0) state.threshold = th;
  $('#hint-imgcol').textContent = state.imgCol;
  $('#hint-codecol').textContent = state.codeCol;
  $('#hint-startrow').textContent = state.startRow;
  $('#modal-settings').classList.add('hidden');
};

$('#btn-clearlog').onclick = () => { $('#console-body').innerHTML = ''; };

log('부품 이미지 자동 매칭 스튜디오 서버판입니다.', 'ok');
log('엑셀과 원본 사진을 업로드한 뒤 [자동 매칭 시작]을 누르세요.', 'dim');
