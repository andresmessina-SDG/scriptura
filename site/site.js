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

  // The initial glints on the first page of a visit.
  try {
    if (!sessionStorage.getItem('scriptura-glint')) { root.classList.add('glint'); sessionStorage.setItem('scriptura-glint', '1'); }
  } catch (e) { /* no storage */ }

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
  // The margins are laid out once per size and paper (layoutField), then
  // painted (paintField). Painting alone is cheap, so the margins can be lit
  // letter by letter: a scribe writes them in on the first page of a visit,
  // a lamp follows the pointer through them, and now and then a letter
  // catches the light like gilt.
  let glyphs = [], fieldW = 0, fieldH = 0, inkRGB = [0, 0, 0], goldRGB = [0, 0, 0];
  function layoutField() {
    const ctx = field.getContext('2d');
    // A pixel budget, as the app's own sheet has: the letters are faint, and a
    // 2x canvas over a large window would hold tens of megabytes for them.
    const w = innerWidth, h = innerHeight;
    const dpr = Math.min(devicePixelRatio || 1, 2, Math.sqrt(12e6 / (w * h)));
    field.width = Math.round(w * dpr); field.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    fieldW = w; fieldH = h; glyphs = [];
    const edge = column.getBoundingClientRect().left;
    const fade = Math.min(FADE, edge * 0.55), band = edge - fade;
    if (!lettersReady || band < MIN_BAND) return;
    const cs = getComputedStyle(root);
    const paper = rgbOf(cs.getPropertyValue('--paper').trim()), ink = rgbOf(cs.getPropertyValue('--ink').trim());
    const gold = rgbOf(cs.getPropertyValue('--gold').trim());
    if (paper.some(isNaN) || ink.some(isNaN)) return;
    inkRGB = ink.map(v => Math.round(v * 255)); goldRGB = gold.some(isNaN) ? inkRGB : gold.map(v => Math.round(v * 255));
    const weightAt = x => {
      const d = Math.min(x, w - x);
      return d <= band ? 1 : d >= band + fade ? 0 : (band + fade - d) / fade;
    };
    // The site sets the letters 20% further off the paper than the app's
    // 3.4 L*, and on light papers, where they faded most, a third more again
    // and 10% on top of that (5.97 L*). Each cap rises with its weight.
    const boost = lum(paper) > 0.5 ? 1.2 * 1.33 * 1.1 : 1.2;
    const alpha = alphaFor(paper, ink, 3.4 * boost, 0.16 * boost), rand = seeded(119), adv = SIZE * TRACK;
    let y = LEAD / 2, row = 0, n = 0;
    while (y < h + LEAD) {
      const greek = row % GREEK_EVERY === GREEK_EVERY - 1, seq = greek ? ALPHA : ALEF;
      // Each line starts a little further along, so the rows never stack.
      let x = -((row * 0.41 * adv) % adv), i = 0;
      while (x < w + adv) {
        n++;
        const wt = weightAt(x);
        if (wt > 0) {
          const a = alpha * wt * (greek ? 0.82 : 1);
          if (n % 97 === 0) glyphs.push({ x, y, row, wt, a: a * 0.92, path: ARAM[Math.floor(rand() * 2)] });
          else if (!greek && n % 11 === 0) glyphs.push({ x, y, row, wt, a: a * 0.8, path: PALEO[i % PALEO.length] });
          else glyphs.push({ x, y, row, wt, a, ch: seq[i % seq.length], greek });
        }
        x += adv; i++;
      }
      y += LEAD; row++;
    }
  }
  const lit = { write: 1, lx: 0, ly: 0, mx: 0, my: 0, lamp: 0, lampTo: 0, glint: null };
  const LAMP = 120;
  function paintField() {
    const ctx = field.getContext('2d'), s = SIZE / 9;
    ctx.clearRect(0, 0, fieldW, fieldH);
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineWidth = 0.9;
    const rows = Math.ceil(fieldH / LEAD) + 1;
    let font = '';
    glyphs.forEach((g, gi) => {
      // The scribe: line after line, top to bottom.
      let k = 1;
      if (lit.write < 1) { const t = lit.write * (rows * 0.55 + 6) - g.row * 0.55; k = Math.max(0, Math.min(1, t / 6)); if (!k) return; }
      // The lamp, and the gilt: both draw a letter toward gold.
      let warm = 0;
      if (lit.lamp > 0.005) { const d = Math.hypot(g.x - lit.lx, g.y - lit.ly); if (d < LAMP) warm = lit.lamp * Math.pow(1 - d / LAMP, 2); }
      if (lit.glint && lit.glint.i === gi) warm = Math.max(warm, lit.glint.v);
      const c = warm ? inkRGB.map((v, j) => Math.round(v + (goldRGB[j] - v) * Math.min(1, warm * 1.1))) : inkRGB;
      const a = Math.min(0.55, g.a * k * (1 + warm * 4));
      const rgba = `rgba(${c.join(',')},${a})`;
      if (g.path) { ctx.strokeStyle = rgba; ctx.beginPath(); g.path(ctx, g.x, g.y, s); ctx.stroke(); return; }
      const f = g.greek ? `${SIZE}px "S Scripture", "Noto Serif", serif` : `${SIZE}px "S Hebrew", "Noto Serif Hebrew", serif`;
      if (f !== font) { ctx.font = f; font = f; }
      ctx.fillStyle = rgba; ctx.fillText(g.ch, g.x, g.y);
    });
  }
  function drawField() { layoutField(); paintField(); drawStrip(); }

  // Where the margins are too narrow for the field, one line of it runs
  // across the top of the footer: Hebrew written right to left, Greek under
  // it left to right, inked in once a visit when it comes into view.
  const strip = el('canvas', 'abc-strip');
  strip.setAttribute('aria-hidden', 'true');
  const colophon = document.querySelector('.colophon');
  if (colophon) colophon.prepend(strip);
  let stripWrite = 1, stripT0 = 0, stripRaf = 0;
  function drawStrip() {
    if (!colophon || !lettersReady || !strip.clientWidth) return;
    const w = strip.clientWidth, h = strip.clientHeight, dpr = Math.min(devicePixelRatio || 1, 2);
    strip.width = Math.round(w * dpr); strip.height = Math.round(h * dpr);
    const ctx = strip.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    const cs = getComputedStyle(root), paper = rgbOf(cs.getPropertyValue('--paper').trim()), ink = rgbOf(cs.getPropertyValue('--ink').trim());
    if (paper.some(isNaN) || ink.some(isNaN)) return;
    const boost = lum(paper) > 0.5 ? 1.2 * 1.33 * 1.1 : 1.2, a = alphaFor(paper, ink, 3.4 * boost, 0.16 * boost);
    const rgb = ink.map(v => Math.round(v * 255)).join(','), adv = SIZE * TRACK, n = Math.floor(w / adv);
    const off = (w - (n - 1) * adv) / 2;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    [[ALEF, `${SIZE}px "S Hebrew", "Noto Serif Hebrew", serif`, h * 0.32, true], [ALPHA, `${SIZE}px "S Scripture", "Noto Serif", serif`, h * 0.74, false]].forEach(([seq, font, y, rtl], line) => {
      ctx.font = font;
      for (let i = 0; i < n; i++) {
        const order = i / n, k = Math.max(0, Math.min(1, (stripWrite * 1.35 - order) / 0.35));
        if (!k) continue;
        const x = rtl ? w - off - i * adv : off + i * adv;
        ctx.fillStyle = `rgba(${rgb},${a * k * (line ? 0.82 : 1) * 1.6})`;
        ctx.fillText(seq[i % seq.length], x, y);
      }
    });
  }
  function stripTick(now) {
    stripWrite = Math.min(1, (now - stripT0) / 1800); drawStrip();
    stripRaf = stripWrite < 1 ? requestAnimationFrame(stripTick) : 0;
  }
  if (colophon && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => {
      if (!es.some(e => e.isIntersecting)) return;
      io.disconnect();
      let first = false;
      try { first = !sessionStorage.getItem('scriptura-strip'); sessionStorage.setItem('scriptura-strip', '1'); } catch (e) { /* no storage */ }
      if (first && !still.matches && lettersReady) { stripWrite = 0; stripT0 = performance.now(); stripRaf = requestAnimationFrame(stripTick); }
      else drawStrip();
    }, { threshold: 0.6 });
    io.observe(strip);
  }

  // One loop serves all three, and stops when nothing is moving.
  const moving = () => !still.matches;
  let raf = 0, writeT0 = 0;
  function tick(now) {
    raf = 0;
    if (lit.write < 1) lit.write = Math.min(1, (now - writeT0) / 2200);
    lit.lamp += (lit.lampTo - lit.lamp) * 0.12;
    lit.lx += (lit.mx - lit.lx) * 0.25; lit.ly += (lit.my - lit.ly) * 0.25;
    if (lit.glint) {
      const t = (now - lit.glint.t0) / 2400;
      lit.glint.v = t < 0.3 ? Math.sin(t / 0.3 * Math.PI / 2) * 0.9 : t < 1 ? Math.cos((t - 0.3) / 0.7 * Math.PI / 2) * 0.9 : 0;
      if (t >= 1) lit.glint = null;
    }
    paintField();
    if (lit.write < 1 || Math.abs(lit.lampTo - lit.lamp) > 0.005 || (lit.lamp > 0.005 && Math.hypot(lit.mx - lit.lx, lit.my - lit.ly) > 0.5) || lit.glint) wake();
  }
  const wake = () => { if (!raf) raf = requestAnimationFrame(tick); };
  // The lamp: only a mouse, only in the margins.
  addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse' || !moving() || !glyphs.length) return;
    const edge = column.getBoundingClientRect().left;
    const inMargin = e.clientX < edge || e.clientX > fieldW - edge;
    if (lit.lamp < 0.01 && inMargin) { lit.lx = e.clientX; lit.ly = e.clientY; }
    lit.mx = e.clientX; lit.my = e.clientY; lit.lampTo = inMargin ? 1 : 0;
    wake();
  }, { passive: true });
  document.addEventListener('pointerleave', () => { lit.lampTo = 0; wake(); });
  // The gilt: one letter in the margins, rarely, faintly. Never while the
  // tab is hidden, never with reduced motion.
  (function glintLater() {
    setTimeout(() => {
      if (moving() && document.visibilityState === 'visible' && glyphs.length && !lit.glint) {
        const pool = glyphs.map((g, i) => [g, i]).filter(([g]) => g.wt > 0.7 && !g.path);
        if (pool.length) { lit.glint = { i: pool[Math.floor(Math.random() * pool.length)][1], t0: performance.now(), v: 0 }; wake(); }
      }
      glintLater();
    }, 6000 + Math.random() * 6000);
  })();
  function firstPaint() {
    lettersReady = true; layoutField();
    let first = false;
    try { first = !sessionStorage.getItem('scriptura-scribe'); sessionStorage.setItem('scriptura-scribe', '1'); } catch (e) { /* no storage */ }
    if (first && moving() && glyphs.length) { lit.write = 0; writeT0 = performance.now() + 250; wake(); }
    else paintField();
    drawStrip();
  }
  let resizing = 0;
  addEventListener('resize', () => { clearTimeout(resizing); resizing = setTimeout(drawField, 120); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawField);
  Promise.all([document.fonts.load(`${SIZE}px "S Hebrew"`, 'אב'), document.fonts.load(`${SIZE}px "S Scripture"`, 'αβ')])
    .catch(() => {}).then(firstPaint);

  const KEYS = ['--paper', '--ink', '--gold', '--blue', 'color-scheme'];
  let chosen = null;
  try { chosen = (JSON.parse(localStorage.getItem('scriptura-paper')) || {}).name || null; } catch (e) { /* no storage */ }

  // A chosen paper crossfades in, and the phone's bar takes its colour.
  // With room to move, the new paper spreads from the chip like ink.
  function choosePaper(name, chip) {
    if (!document.startViewTransition) { applyPaper(name); return; }
    const ink = chip && !still.matches;
    root.classList.toggle('ink', !!ink);
    const t = document.startViewTransition(() => applyPaper(name));
    if (ink) {
      const b = chip.getBoundingClientRect(), x = b.left + b.width / 2, y = b.top + b.height / 2;
      const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      t.ready.then(() => root.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
        { duration: 520, easing: 'cubic-bezier(0.23, 1, 0.32, 1)', pseudoElement: '::view-transition-new(root)' })).catch(() => {});
    }
    t.finished.finally(() => root.classList.remove('ink'));
  }
  const bars = [...document.querySelectorAll('meta[name="theme-color"]')], barsWere = bars.map(m => m.content);
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
    // A phone crop keeps its own width condition.
    const media = p ? (isDark(p[1]) ? 'all' : 'not all') : '(prefers-color-scheme: dark)';
    document.querySelectorAll('picture source[data-dark]').forEach(s => {
      const when = s.dataset.when;
      s.media = !when ? media : media === 'all' ? when : media === 'not all' ? 'not all' : `${when} and ${media}`;
    });
    bars.forEach((m, i) => { m.content = p ? p[1] : barsWere[i]; });
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
  box.addEventListener('click', e => { const c = e.target.closest('.chip'); if (c) choosePaper(c.dataset.p, c); });
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
  // On a phone the panel can sit a screen below the word: bring it
  // into view, so a tap is seen to do something.
  const phone = matchMedia('(max-width: 759px)');
  const lexBox = document.getElementById('lex');
  const showPanel = () => {
    if (!phone.matches) return;
    const r = lexBox.getBoundingClientRect();
    if (r.top > innerHeight - 120) lexBox.scrollIntoView({ block: 'nearest', behavior: still.matches ? 'auto' : 'smooth' });
  };
  const activate = e => {
    const w = e.target.closest('.w'), v = e.target.closest('.vn');
    if (w) openWord(w); else if (v) openVerse(+v.dataset.v);
    if (w || v) showPanel();
  };
  {
    const panes = [...document.querySelectorAll('.pane')], win0 = document.querySelector('.win');
    win0.classList.add('one');
    const pick = el('div', 'seg pane-pick');
    pick.setAttribute('role', 'radiogroup');
    panes.forEach((p, i) => {
      const b = el('button', null, p.querySelector('.ph').textContent.replace(/\s*▾\s*$/, ''));
      b.type = 'button'; b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(i === 0)); b.title = b.textContent;
      b.addEventListener('click', () => {
        pick.querySelectorAll('button').forEach((x, j) => x.setAttribute('aria-checked', String(j === i)));
        win0.classList.toggle('right', i === 1);
      });
      pick.append(b);
    });
    win0.querySelector('.bar').after(pick);
  }
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
  let dwell = 0, hidAt = -1e9;
  left.addEventListener('pointerover', e => {
    const w = e.target.closest('.w');
    if (!w || e.pointerType !== 'mouse') return;
    clearTimeout(dwell);
    // Once a gloss has shown, the next word's comes at once, unanimated.
    const warm = performance.now() - hidAt < 400;
    gloss.classList.toggle('instant', warm);
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
    }, warm ? 0 : 350);
  });
  left.addEventListener('pointerout', e => {
    if (e.target.closest('.w')) { clearTimeout(dwell); if (!gloss.hidden) hidAt = performance.now(); gloss.hidden = true; }
  });

  // Open on the Word: the entry John 1 is about, in every language, lit as
  // if someone had just touched it.
  const opening = [...left.querySelectorAll('.w')].find(w => (DATA.entries[w.dataset.k].n || w.dataset.k) === 'G3056')
    || left.querySelector('.w');
  if (opening) {
    openWord(opening);
    document.getElementById('lex').classList.add('enter');
  }

  // Small live touches: the window's own Reading mode, Presentation and a
  // verse card, as the app has them. Built once the demo data is in.
  document.addEventListener('DOMContentLoaded', () => {
    const UI = window.DEMOS && window.DEMOS.ui[['es', 'ru'].includes(root.lang) ? root.lang : 'en'];
    if (!UI) return;
    // A phone cannot run the download: step 1 says so, offers to send
    // the page on, and still lets anyone (a Linux phone, say) download.
    {
      const P = window.DEMOS.phonedl[['es', 'ru'].includes(root.lang) ? root.lang : 'en'];
      const step = document.querySelector('#install .steps > li'), real = step && step.querySelector('.more .go');
      if (real) {
        const url = (document.querySelector('link[rel="canonical"]') || {}).href || location.href;
        const box = el('div', 'more phone-dl'), row = el('div', 'row-b');
        box.append(el('b', null, P[0]), el('p', null, P[1]), row);
        if (navigator.share) {
          const sh = el('button', null, P[2]); sh.type = 'button';
          sh.addEventListener('click', () => navigator.share({ title: document.title, url }).catch(() => {}));
          row.append(sh);
        }
        const cp = el('button', null, P[3]); cp.type = 'button';
        cp.addEventListener('click', () => {
          try { navigator.clipboard.writeText(url).then(() => { cp.textContent = P[4]; setTimeout(() => { cp.textContent = P[3]; }, 1800); }, () => {}); } catch (e) { /* no clipboard */ }
        });
        const any = el('a', null, P[5]); any.href = real.href;
        row.append(cp, any);
        step.append(box);
      }
    }
    const bandTitle = k => { const i = document.querySelector(`.band img[src*="/${k}"]`); return i ? i.closest('.band').querySelector('h3').textContent : ''; };
    const rowTitles = [...document.querySelectorAll('.rows .row h3')].map(h => h.textContent);
    const READ = bandTitle('reading'), PRESENT = UI[8], CARD = rowTitles[13] || '', COPY = UI[10];
    const bar = win.querySelector('.bar');
    bar.removeAttribute('aria-hidden');
    bar.querySelectorAll(':scope > svg, .t, .x').forEach(n => n.setAttribute('aria-hidden', 'true'));
    const ICON = {
      read: '<path d="M2.5 3.5h4.2c.8 0 1.3.5 1.3 1.3v8.4c0-.7-.6-1.2-1.3-1.2H2.5zM13.5 3.5H9.3c-.8 0-1.3.5-1.3 1.3v8.4c0-.7.6-1.2 1.3-1.2h4.2z"/>',
      present: '<rect x="1.8" y="2.8" width="12.4" height="8.4" rx="1.2"/><path d="M8 11.2v2.6M5.5 13.8h5"/>',
      card: '<rect x="1.8" y="3" width="12.4" height="10" rx="1.2"/><path d="m3.5 11 3-3.2 2.2 2.2 1.6-1.6 2.2 2.6"/><circle cx="10.6" cy="5.9" r="1"/>',
    };
    const tool = (k, label, fn) => {
      const b = el('button', 'touch');
      b.type = 'button'; b.title = label; b.setAttribute('aria-label', label);
      b.innerHTML = `<svg viewBox="0 0 16 16" aria-hidden="true">${ICON[k]}</svg>`;
      b.addEventListener('click', fn);
      bar.querySelector('.x').before(b);
      return b;
    };
    const verseText = v => DATA.left[v - 1].map(t => t[0]).join('').replace(/\s+/g, ' ').trim();
    const morph = fn => (document.startViewTransition && !still.matches) ? document.startViewTransition(fn) : fn();

    // Reading mode: the chrome goes and the text stays, on the paper.
    const exitRead = el('button', 'touch-exit', UI[7]);
    exitRead.type = 'button'; win.append(exitRead);
    const setReading = on => {
      // Focus moves once the window has changed, inside the transition's update.
      morph(() => { win.classList.toggle('reading', on); (on ? exitRead : readBtn).focus({ preventScroll: true }); });
    };
    const readBtn = tool('read', READ, () => setReading(true));
    exitRead.addEventListener('click', () => setReading(false));
    win.addEventListener('keydown', e => { if (e.key === 'Escape' && win.classList.contains('reading')) setReading(false); });

    // Presentation: the selected verse, full screen in large type.
    const stage = el('div', 'present'); stage.tabIndex = -1;
    stage.setAttribute('role', 'dialog'); stage.setAttribute('aria-label', PRESENT); stage.hidden = true;
    const pv = el('p', 'present-v'), pr = el('p', 'present-r');
    const exitP = el('button', 'touch-exit', UI[9]); exitP.type = 'button';
    stage.append(pv, pr, exitP); document.body.append(stage);
    let pvn = 1;
    const showV = v => { pvn = Math.max(1, Math.min(DATA.left.length, v)); pv.textContent = verseText(pvn); pr.textContent = `${DATA.ref}:${pvn}`; };
    const endP = () => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); stage.hidden = true; presentBtn.focus({ preventScroll: true }); };
    const presentBtn = tool('present', PRESENT, () => {
      showV(state.verse || 1); stage.hidden = false; stage.focus();
      if (stage.requestFullscreen) stage.requestFullscreen().catch(() => {});
    });
    exitP.addEventListener('click', endP);
    document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && !stage.hidden) endP(); });
    stage.addEventListener('keydown', e => {
      if (e.key === 'Escape') endP();
      else if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') { e.preventDefault(); showV(pvn + 1); }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); showV(pvn - 1); }
    });

    // A verse as an image: drawn on the chosen paper with the gold initial.
    const cardbox = el('dialog', 'zoombox cardbox'); cardbox.setAttribute('aria-label', CARD);
    const cimg = el('img'); cimg.alt = '';
    const crow = el('div', 'card-row'), copyB = el('button', 'copy', COPY), closeB = el('button', 'copy', '×');
    copyB.type = closeB.type = 'button'; closeB.setAttribute('aria-label', 'Close');
    crow.append(copyB, closeB); cardbox.append(cimg, crow); document.body.append(cardbox);
    let blob = null;
    tool('card', CARD, async () => {
      const v = state.verse || 1, cs = getComputedStyle(root), c = el('canvas');
      c.width = 1200; c.height = 630;
      const x = c.getContext('2d'), paper = cs.getPropertyValue('--paper').trim(), ink = cs.getPropertyValue('--ink').trim(), gold = cs.getPropertyValue('--gold').trim();
      const serif = root.lang === 'ru' ? '"S Scripture", "Noto Serif", serif' : '"S Scripture", "Noto Serif", Georgia, serif';
      await document.fonts.load(`44px ${serif}`, 'Aa');
      x.fillStyle = paper; x.fillRect(0, 0, 1200, 630);
      const text = verseText(v), first = text[0], rest = text.slice(1);
      x.font = `500 132px ${serif}`; x.textBaseline = 'alphabetic';
      const capW = x.measureText(first).width + 18;
      x.font = `44px ${serif}`;
      const words = rest.split(' '), lines = []; let line = '', lead = 64;
      for (const w of words) {
        const max = lines.length < 2 ? 1008 - capW : 1008;
        if (x.measureText(line + w).width > max && line) { lines.push(line.trim()); line = ''; }
        line += w + ' ';
      }
      lines.push(line.trim());
      // The text sits in the middle of the card, the reference at its foot.
      const shown = lines.slice(0, 6), y = Math.round((520 - shown.length * lead) / 2) + 44 + 20;
      x.fillStyle = gold; x.font = `500 132px ${serif}`; x.fillText(first, 96, y + lead);
      x.fillStyle = ink; x.font = `44px ${serif}`;
      shown.forEach((l, i) => x.fillText(l, i < 2 ? 96 + capW : 96, y + i * lead));
      x.fillStyle = gold; x.font = '600 26px "S Sans", system-ui, sans-serif';
      x.fillText(`${DATA.ref}:${v}`, 96, 560);
      c.toBlob(b => { blob = b; cimg.src = URL.createObjectURL(b); cimg.alt = `${DATA.ref}:${v}`; copyB.textContent = COPY; copyB.disabled = false; cardbox.showModal(); }, 'image/png');
    });
    copyB.addEventListener('click', e => {
      e.stopPropagation();
      try { navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]).then(() => { copyB.textContent = S.copied; }, () => { copyB.disabled = true; }); }
      catch (err) { copyB.disabled = true; }
    });
    closeB.addEventListener('click', () => cardbox.close());
    cardbox.addEventListener('click', e => { if (e.target === cardbox) cardbox.close(); });
  });

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

  // Download glides down to the install steps. A keyboard press
  // (no click detail) and reduced motion still jump at once.
  const install = document.getElementById('install');
  if (install) document.addEventListener('click', e => {
    const a = e.target.closest('a[href$="#install"]');
    if (!a || e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    const glide = e.detail > 0 && !still.matches;
    install.scrollIntoView({ behavior: glide ? 'smooth' : 'auto', block: 'start' });
    install.tabIndex = -1;
    install.focus({ preventScroll: true });
    try { history.replaceState(null, '', '#install'); } catch (err) { /* no history */ }
  });

  // ── copy ──
  const copyBtn = document.getElementById('copy'), cmd = document.getElementById('cmd');
  // The label lives in its own span so it can blur across.
  const lbl = el('span', 'lbl', copyBtn ? copyBtn.textContent : '');
  if (copyBtn) copyBtn.replaceChildren(lbl);
  const relabel = t => {
    if (still.matches) { lbl.textContent = t; return; }
    copyBtn.classList.add('swap');
    setTimeout(() => { lbl.textContent = t; copyBtn.classList.remove('swap'); }, 120);
  };
  if (copyBtn) copyBtn.addEventListener('click', () => {
    const select = () => {
      const r = document.createRange(); r.selectNodeContents(cmd);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      relabel(S.press_ctrl_c);
    };
    const done = () => { relabel(S.copied); setTimeout(() => relabel(S.copy), 1600); };
    try { navigator.clipboard.writeText(cmd.textContent).then(done, select); } catch (e) { select(); }
  });
})();
