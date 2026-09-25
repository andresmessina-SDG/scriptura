// The Scriptura website: the header's pickers, the working reading pane, the
// enlarged screenshots and the copy button. Everything it reads is in the
// page; it fetches nothing.
(() => {
  'use strict';
  const { text: DATA, strings: S, notfound: NOTFOUND } = JSON.parse(document.getElementById('site-data').textContent);
  const root = document.documentElement;
  const el = (tag, cls, txt) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  };
  const still = matchMedia('(prefers-reduced-motion: reduce)');

  // ── papers: appearance_page.py's chips, pane.py's ink rule ──
  const PAPERS = [
    ['Paper', '#f7f4ee', '#2b2620'], ['White', '#fbfbfb', null], ['Sepia', '#f8f1e3', null], ['Green', '#dce8d0', null],
    ['Slate', '#1e1e1e', '#e8e0d4'], ['Charcoal', '#2a2622', null], ['Black', '#000000', null],
  ];
  const rgbOf = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  const hexOf = a => '#' + a.map(v => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
  const isDark = h => { const [r, g, b] = rgbOf(h); return 0.299 * r + 0.587 * g + 0.114 * b < 0.5; };
  function rgbToHls(r, g, b) {
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    if (mx === mn) return [0, l, 0];
    const d = mx - mn, s = l <= 0.5 ? d / (mx + mn) : d / (2 - mx - mn);
    const h = mx === r ? (g - b) / d : mx === g ? 2 + (b - r) / d : 4 + (r - g) / d;
    return [((h / 6) % 1 + 1) % 1, l, s];
  }
  function hlsToRgb(h, l, s) {
    if (s === 0) return [l, l, l];
    const m2 = l <= 0.5 ? l * (1 + s) : l + s - l * s, m1 = 2 * l - m2;
    const v = hue => {
      hue = ((hue % 1) + 1) % 1;
      if (hue < 1 / 6) return m1 + (m2 - m1) * hue * 6;
      if (hue < 0.5) return m2;
      if (hue < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - hue) * 6;
      return m1;
    };
    return [v(h + 1 / 3), v(h), v(h - 1 / 3)];
  }
  function autoInk(paper) {
    if (isDark(paper)) return '#e8e0d4';
    const [h, , s] = rgbToHls(...rgbOf(paper));
    if (s < 0.06) return '#1a1a1a';
    return hexOf(hlsToRgb(h, 0.16, Math.min(s, 0.55)));
  }
  // ── the margins: the Today page's abecedary (scribal_field.py), plain ──
  // The twenty-two Hebrew letters in order, line after line, every fourth
  // line Greek; every eleventh Hebrew letter in Paleo-Hebrew and about one
  // glyph in a hundred in Imperial Aramaic, both drawn as paths. In ORDER, so
  // nothing spells anything. Kept to the margins, fading out before the
  // column, at one perceived weight on whatever paper is chosen.
  const SIZE = 17, LEAD = 44, TRACK = 1.62, GREEK_EVERY = 4, FADE = 110, MIN_BAND = 26;
  const FINALS = [0x05da, 0x05dd, 0x05df, 0x05e3, 0x05e5];
  const ALEF = [], ALPHA = [];
  for (let c = 0x05d0; c <= 0x05ea; c++) if (!FINALS.includes(c)) ALEF.push(String.fromCharCode(c));
  for (let c = 0x03b1; c <= 0x03c9; c++) if (c !== 0x03c2) ALPHA.push(String.fromCharCode(c));
  const lin = c => c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const lstar = y => y > 0.008856 ? 116 * Math.cbrt(y) - 16 : 903.3 * y;
  // The alpha at which ink over paper sits `weight` L* off the paper: a flat
  // alpha reads heavier on dark papers than on light ones.
  function alphaFor(paper, ink, weight = 3.4, cap = 0.16) {
    const base = lstar(lum(paper));
    let lo = 0, hi = cap;
    for (let i = 0; i < 60; i++) {
      const m = (lo + hi) / 2, mix = paper.map((p, k) => p * (1 - m) + ink[k] * m);
      if (Math.abs(lstar(lum(mix)) - base) < weight) lo = m; else hi = m;
    }
    return lo;
  }
  function seeded(seed) {
    return () => {
      seed = seed + 0x6D2B79F5 | 0;
      let r = Math.imul(seed ^ seed >>> 15, 1 | seed);
      r = r + Math.imul(r ^ r >>> 7, 61 | r) ^ r;
      return ((r ^ r >>> 14) >>> 0) / 4294967296;
    };
  }
  const PALEO = [   // ayin, taw, mem, lamed, aleph, shin, bet, qof
    (c, x, y, s) => { c.arc(x, y, 3.4 * s, 0, 2 * Math.PI); },
    (c, x, y, s) => { c.moveTo(x - 3.2 * s, y - 3.2 * s); c.lineTo(x + 3.2 * s, y + 3.2 * s); c.moveTo(x + 3.2 * s, y - 3.2 * s); c.lineTo(x - 3.2 * s, y + 3.2 * s); },
    (c, x, y, s) => { c.moveTo(x - 4 * s, y - 3 * s); [-2, 0, 2, 4].forEach((dx, i) => c.lineTo(x + dx * s, y + (i % 2 === 0 ? 3 : -3) * s)); },
    (c, x, y, s) => { c.moveTo(x + 1.4 * s, y - 4.4 * s); c.lineTo(x - 0.6 * s, y + 2.2 * s); c.bezierCurveTo(x - 1.2 * s, y + 4.4 * s, x - 3.4 * s, y + 4.6 * s, x - 3.8 * s, y + 2.6 * s); },
    (c, x, y, s) => { c.moveTo(x - 4.2 * s, y - 3.4 * s); c.lineTo(x + s, y - 0.6 * s); c.moveTo(x - 4.2 * s, y + s); c.lineTo(x + s, y - 0.6 * s); c.moveTo(x - 1.4 * s, y - 2 * s); c.lineTo(x + 3 * s, y + 4 * s); },
    (c, x, y, s) => { c.moveTo(x - 3.6 * s, y - 3 * s); c.lineTo(x - 1.8 * s, y + 3 * s); c.lineTo(x, y - 3 * s); c.lineTo(x + 1.8 * s, y + 3 * s); c.lineTo(x + 3.6 * s, y - 3 * s); },
    (c, x, y, s) => { c.moveTo(x + 2.6 * s, y - 3.4 * s); c.lineTo(x - 2 * s, y - 3.4 * s); c.bezierCurveTo(x - 3.6 * s, y - 3.4 * s, x - 3.6 * s, y - 0.2 * s, x - 2 * s, y - 0.2 * s); c.lineTo(x + 1.2 * s, y - 0.2 * s); c.lineTo(x - 3 * s, y + 3.8 * s); },
    (c, x, y, s) => { c.arc(x, y - 1.4 * s, 2.2 * s, 0, 2 * Math.PI); c.moveTo(x, y + 0.8 * s); c.lineTo(x, y + 4.4 * s); },
  ];
  const ARAM = [    // aleph, dalet
    (c, x, y, s) => { c.moveTo(x + 3.2 * s, y - 4 * s); c.bezierCurveTo(x - 1.6 * s, y - 2.4 * s, x - 3.2 * s, y + 0.8 * s, x - 1.6 * s, y + 4 * s); c.moveTo(x + 0.6 * s, y - 3.2 * s); c.lineTo(x + 3.4 * s, y + 4 * s); },
    (c, x, y, s) => { c.moveTo(x - 3 * s, y - 3.2 * s); c.bezierCurveTo(x + 2 * s, y - 3.6 * s, x + 2.6 * s, y - 0.6 * s, x - 0.4 * s, y + 0.6 * s); c.lineTo(x - 1.2 * s, y + 4.2 * s); },
  ];
  const field = document.getElementById('field'), column = document.querySelector('main');
  let lettersReady = false;
  function drawField() {
    const ctx = field.getContext('2d');
    // A pixel budget, as the app's own sheet has: the letters are faint, and a
    // 2x canvas over a large window would hold tens of megabytes for them.
    const w = innerWidth, h = innerHeight;
    const dpr = Math.min(devicePixelRatio || 1, 2, Math.sqrt(12e6 / (w * h)));
    field.width = Math.round(w * dpr); field.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const edge = column.getBoundingClientRect().left;
    const fade = Math.min(FADE, edge * 0.55), band = edge - fade;
    if (!lettersReady || band < MIN_BAND) return;
    const cs = getComputedStyle(root);
    const paper = rgbOf(cs.getPropertyValue('--paper').trim()), ink = rgbOf(cs.getPropertyValue('--ink').trim());
    if (paper.some(isNaN) || ink.some(isNaN)) return;
    const rgba = a => `rgba(${ink.map(v => Math.round(v * 255)).join(',')},${a})`;
    const weightAt = x => {
      const d = Math.min(x, w - x);
      return d <= band ? 1 : d >= band + fade ? 0 : (band + fade - d) / fade;
    };
    const alpha = alphaFor(paper, ink), rand = seeded(119), adv = SIZE * TRACK, s = SIZE / 9;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineWidth = 0.9;
    let y = LEAD / 2, row = 0, n = 0;
    while (y < h + LEAD) {
      const greek = row % GREEK_EVERY === GREEK_EVERY - 1, seq = greek ? ALPHA : ALEF;
      ctx.font = greek ? `${SIZE}px "S Scripture", "Noto Serif", serif` : `${SIZE}px "S Hebrew", "Noto Serif Hebrew", serif`;
      // Each line starts a little further along, so the rows never stack.
      let x = -((row * 0.41 * adv) % adv), i = 0;
      while (x < w + adv) {
        n++;
        const wt = weightAt(x);
        if (wt > 0) {
          const a = alpha * wt * (greek ? 0.82 : 1);
          if (n % 97 === 0) {
            ctx.strokeStyle = rgba(a * 0.92); ctx.beginPath(); ARAM[Math.floor(rand() * 2)](ctx, x, y, s); ctx.stroke();
          } else if (!greek && n % 11 === 0) {
            ctx.strokeStyle = rgba(a * 0.8); ctx.beginPath(); PALEO[i % PALEO.length](ctx, x, y, s); ctx.stroke();
          } else {
            ctx.fillStyle = rgba(a); ctx.fillText(seq[i % seq.length], x, y);
          }
        }
        x += adv; i++;
      }
      y += LEAD; row++;
    }
  }
  let resizing = 0;
  addEventListener('resize', () => { clearTimeout(resizing); resizing = setTimeout(drawField, 120); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawField);
  Promise.all([document.fonts.load(`${SIZE}px "S Hebrew"`, 'אב'), document.fonts.load(`${SIZE}px "S Scripture"`, 'αβ')])
    .catch(() => {}).then(() => { lettersReady = true; drawField(); });

  const KEYS = ['--paper', '--ink', '--gold', '--blue', 'color-scheme'];
  let chosen = null;
  try { chosen = (JSON.parse(localStorage.getItem('scriptura-paper')) || {}).name || null; } catch (e) { /* no storage */ }

  function applyPaper(name) {
    const p = PAPERS.find(x => x[0] === name);
    KEYS.forEach(k => root.style.removeProperty(k));
    let vars = null;
    if (p) {
      const dark = isDark(p[1]);
      vars = { '--paper': p[1], '--ink': p[2] || autoInk(p[1]), '--gold': dark ? '#d0ac5c' : '#a5822b',
               '--blue': dark ? '#81d0ff' : '#0461be', 'color-scheme': dark ? 'dark' : 'light' };
      for (const k in vars) root.style.setProperty(k, vars[k]);
    }
    chosen = p ? name : null;
    try {
      if (chosen) localStorage.setItem('scriptura-paper', JSON.stringify({ name: chosen, vars }));
      else localStorage.removeItem('scriptura-paper');
    } catch (e) { /* no storage */ }
    document.querySelectorAll('.chip').forEach(c => c.setAttribute('aria-pressed', String(c.dataset.p === (chosen || 'Auto'))));
    // The screenshots follow the paper, as the app does: a dark paper shows
    // the app in dark, and Auto hands the choice back to the system.
    const media = p ? (isDark(p[1]) ? 'all' : 'not all') : '(prefers-color-scheme: dark)';
    document.querySelectorAll('picture source').forEach(s => { s.media = media; });
    drawField();
  }
  const box = document.getElementById('papers') || el('div');
  const auto = el('button', 'chip auto');
  auto.type = 'button'; auto.dataset.p = 'Auto'; auto.title = S.auto_title;
  auto.append(el('span', null, S.papers.Auto));
  box.append(auto);
  for (const [name, bg, ink] of PAPERS) {
    const b = el('button', 'chip', S.papers[name]);
    b.type = 'button'; b.dataset.p = name;
    b.style.background = bg; b.style.color = ink || autoInk(bg);
    box.append(b);
  }
  box.addEventListener('click', e => { const c = e.target.closest('.chip'); if (c) applyPaper(c.dataset.p); });
  applyPaper(chosen);

  // The header's pickers: one open at a time; Escape or a click elsewhere closes.
  const pickers = [...document.querySelectorAll('.head [aria-controls]')]
    .map(btn => ({ btn, pop: document.getElementById(btn.getAttribute('aria-controls')) }));
  const setOpen = (which, open) => {
    pickers.forEach(p => {
      const on = open && p === which;
      p.pop.hidden = !on;
      p.btn.setAttribute('aria-expanded', String(on));
    });
  };
  pickers.forEach(p => p.btn.addEventListener('click', () => setOpen(p, p.pop.hidden)));
  document.addEventListener('keydown', e => {
    const open = pickers.find(p => !p.pop.hidden);
    if (e.key === 'Escape' && open) { setOpen(open, false); open.btn.focus(); }
  });
  document.addEventListener('click', e => {
    const open = pickers.find(p => !p.pop.hidden);
    if (open && !open.pop.contains(e.target) && !open.btn.contains(e.target)) setOpen(open, false);
  });

  if (DATA) readingPane();
  function readingPane() {
  // ── the reading pane ──
  // The first letter of the chapter is the drop cap, in the reading gold. A
  // text that sets its first word in capitals ("EN el principio") reads
  // as a shout once the cap is enlarged, so the rest of that word drops.
  function capped(parent, textIn) {
    const m = textIn.match(/^(\P{L}*)(\p{L})(\p{Lu}*)(.*)$/su);
    if (!m) { parent.append(textIn); return; }
    parent.append(m[1], el('span', 'dc', m[2]), m[3].toLowerCase() + m[4]);
  }
  function verseNum(parent, n) {
    const v = el('span', 'vn', String(n));
    v.dataset.v = String(n); v.tabIndex = 0; v.setAttribute('role', 'button');
    parent.append(v);
  }
  const left = document.getElementById('pane-left'), right = document.getElementById('pane-right');
  DATA.left.forEach((toks, i) => {
    verseNum(left, i + 1);
    toks.forEach(([t, key], j) => {
      const target = key ? el('span', 'w') : left;
      if (key) {
        target.dataset.k = key; target.dataset.v = String(i + 1); target.tabIndex = 0;
        target.setAttribute('role', 'button'); left.append(target);
      }
      if (i === 0 && j === toks.findIndex(x => /\p{L}/u.test(x[0]))) capped(target, t);
      else target.append(t);
    });
    left.append(' ');
  });
  DATA.right.forEach((v, i) => {
    verseNum(right, i + 1);
    if (i === 0) capped(right, v); else right.append(v);
    right.append(' ');
  });

  const panel = document.getElementById('panel'), where = document.getElementById('where');
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const state = { tab: 'entry', key: null, verse: 1, ref: 0 };

  function entryView() {
    const e = DATA.entries[state.key];
    const out = [];
    const hd = el('div', 'hd');
    if (e.g) { const g = el('span', 'gk', e.g); g.lang = 'grc'; hd.append(g); }
    if (e.t) hd.append(el('span', 'tr', e.t));
    if (e.p) hd.append(el('span', 'pr', e.p));
    out.push(hd);
    if (e.h) out.push(el('p', 'hw', e.h));
    if (e.d) out.push(el('p', 'df', e.d + '.'));
    if (e.u) out.push(el('p', 'us', `${S.kjv_uses} ${e.u}.`));
    (e.a || []).forEach(p => out.push(el('p', 'df', p)));
    return out;
  }
  function xrefView() {
    const refs = DATA.xrefs[state.verse - 1] || [];
    if (!refs.length) return [el('p', 'note', S.xrefs_none)];
    const chips = el('div', 'xchips');
    refs.forEach((r, i) => {
      const c = el('button', 'xchip', r.r);
      c.type = 'button'; c.dataset.i = String(i);
      c.setAttribute('aria-pressed', String(i === state.ref));
      chips.append(c);
    });
    const out = [chips];
    const r = refs[state.ref];
    if (r) {
      const q = el('blockquote', 'peek');
      q.append(el('b', null, r.r + ' '), r.t);
      out.push(q);
    }
    return out;
  }
  function voicesView() {
    const out = [];
    if (S.voices_note) out.push(el('p', 'note', S.voices_note));
    (DATA.voices[state.verse - 1] || []).forEach(q => {
      const a = el('article', 'voice');
      a.lang = 'en';
      const who = el('p', 'who');
      who.append(el('b', null, q.a), ` · ${q.y}`);
      a.append(who, el('p', 'src', q.s), el('p', 'q', q.t));
      out.push(a);
    });
    return out;
  }
  function render() {
    tabs.forEach(t => {
      const on = t.dataset.tab === state.tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      if (on) panel.setAttribute('aria-labelledby', t.id);
    });
    where.textContent = state.tab === 'entry'
      ? S.entry.replace('{n}', DATA.entries[state.key].n || state.key)
      : `${DATA.ref}:${state.verse}`;
    panel.replaceChildren(...(state.tab === 'entry' ? entryView()
      : state.tab === 'xrefs' ? xrefView() : voicesView()));
    panel.scrollTop = 0;
    document.querySelectorAll('.w').forEach(w => w.classList.toggle('on', state.tab === 'entry' && w.dataset.k === state.key));
    document.querySelectorAll('.vn').forEach(v => v.classList.toggle('on', state.tab !== 'entry' && v.dataset.v === String(state.verse)));
  }
  function openWord(w) { Object.assign(state, { tab: 'entry', key: w.dataset.k, verse: +w.dataset.v }); render(); }
  function openVerse(n) {
    Object.assign(state, { verse: n, ref: 0, tab: state.tab === 'entry' ? 'xrefs' : state.tab });
    render();
  }
  const activate = e => {
    const w = e.target.closest('.w'), v = e.target.closest('.vn');
    if (w) openWord(w); else if (v) openVerse(+v.dataset.v);
  };
  [left, right].forEach(p => {
    p.addEventListener('click', activate);
    p.addEventListener('keydown', e => {
      if ((e.key === 'Enter' || e.key === ' ') && e.target.closest('.w, .vn')) { e.preventDefault(); activate(e); }
    });
  });
  tabs.forEach(t => t.addEventListener('click', () => { state.tab = t.dataset.tab; render(); }));
  document.querySelector('.tabs').addEventListener('keydown', e => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0 || (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft')) return;
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    next.focus(); next.click();
  });
  panel.addEventListener('click', e => {
    const c = e.target.closest('.xchip');
    if (c) { state.ref = +c.dataset.i; render(); }
  });

  // Dwell on a word and its gloss rises above it, as the app's hover
  // preview does; it never takes the click's place.
  const gloss = document.getElementById('gloss'), win = document.querySelector('.win');
  let dwell = 0;
  left.addEventListener('pointerover', e => {
    const w = e.target.closest('.w');
    if (!w || e.pointerType !== 'mouse') return;
    clearTimeout(dwell);
    dwell = setTimeout(() => {
      const d = DATA.entries[w.dataset.k];
      // English readers get Dodson's gloss; the others their own dictionary's
      // headword, since the gloss is English.
      gloss.textContent = [d.g, DATA.lookup === 'strongs' ? d.b : d.h].filter(Boolean).join(' · ');
      gloss.hidden = false;
      const wr = w.getBoundingClientRect(), br = win.getBoundingClientRect();
      const x = Math.min(Math.max(wr.left - br.left, 8), br.width - gloss.offsetWidth - 8);
      gloss.style.left = `${x}px`;
      gloss.style.top = `${wr.top - br.top - gloss.offsetHeight - 6}px`;
    }, 350);
  });
  left.addEventListener('pointerout', e => {
    if (e.target.closest('.w')) { clearTimeout(dwell); gloss.hidden = true; }
  });

  // Open on the Word: the entry John 1 is about, in every language, lit as
  // if someone had just touched it.
  const opening = [...left.querySelectorAll('.w')].find(w => (DATA.entries[w.dataset.k].n || w.dataset.k) === 'G3056')
    || left.querySelector('.w');
  if (opening) {
    openWord(opening);
    if (!still.matches) document.getElementById('lex').classList.add('enter');
  }

  }

  // ── screenshots, full size ──
  const zoombox = document.getElementById('zoombox'), zoomimg = document.getElementById('zoomimg');
  document.querySelectorAll('.zoom').forEach(b => b.addEventListener('click', () => {
    const img = b.querySelector('img');
    zoomimg.src = img.currentSrc || img.src;
    zoomimg.alt = img.alt;
    zoombox.showModal();
  }));
  if (zoombox) zoombox.addEventListener('click', () => zoombox.close());

  // ── the missing page: one file for every address, in the reader's language ──
  if (NOTFOUND) {
    const m = location.pathname.match(/\/scriptura\/(es|ru)\//);
    const asked = (navigator.language || '').slice(0, 2);
    const lang = m ? m[1] : (NOTFOUND[asked] ? asked : 'en');
    const t = NOTFOUND[lang];
    if (lang !== 'en') {
      root.lang = lang;
      document.title = t.title;
      document.querySelectorAll('[data-nf]').forEach(n => { n.textContent = t[n.dataset.nf]; });
      const verse = document.querySelector('[data-nf-verse]');
      verse.replaceChildren(el('span', 'dropcap', t.verse[0]), t.verse.slice(1));
      document.querySelectorAll('[data-nf-href="home"]').forEach(a => { a.href = t.root; });
      document.querySelectorAll('[data-nf-href="news"]').forEach(a => { a.href = t.root + 'whats-new/'; });
    }
  }

  // ── copy ──
  const copyBtn = document.getElementById('copy'), cmd = document.getElementById('cmd');
  if (copyBtn) copyBtn.addEventListener('click', () => {
    const select = () => {
      const r = document.createRange(); r.selectNodeContents(cmd);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      copyBtn.textContent = S.press_ctrl_c;
    };
    const done = () => { copyBtn.textContent = S.copied; setTimeout(() => { copyBtn.textContent = S.copy; }, 1600); };
    try { navigator.clipboard.writeText(cmd.textContent).then(done, select); } catch (e) { select(); }
  });
})();
