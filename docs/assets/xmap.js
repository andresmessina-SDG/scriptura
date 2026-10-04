// The cross-reference map. Every chapter of the 66 books sits on one
// line, Genesis to Revelation; every strong link between two chapters is an
// arc of gold above it. Point at a book, or focus the map and use the arrow
// keys, and its arcs light while the rest step back.
(() => {
  'use strict';
  const X = window.XMAP, canvas = document.getElementById('xmap-c');
  if (!X || !canvas) return;
  const root = document.documentElement, read = document.getElementById('xmap-read');
  const lang = root.lang in X.names ? root.lang : 'en';
  const names = X.names[lang], fmt = new Intl.NumberFormat(lang);
  const T = (b, n, m) => X.read[lang].replace('{book}', `<b>${b}</b>`).replace('{n}', n).replace('{m}', m);
  const still = matchMedia('(prefers-reduced-motion: reduce)');

  // Arcs: [from chapter, to chapter, weight], faint first so the strong lie on top.
  const raw = atob(X.arcs), arcs = [];
  for (let i = 0; i < raw.length; i += 5) {
    const u = k => raw.charCodeAt(i + k);
    arcs.push([u(0) | u(1) << 8, u(2) | u(3) << 8, u(4)]);
  }
  const TOTAL = X.chapters.reduce((a, b) => a + b, 0);
  const start = []; X.chapters.reduce((s, c, i) => (start[i] = s, s + c), 0);
  const bookOf = ch => { let b = 0; while (b < 65 && start[b + 1] <= ch) b++; return b; };
  const arcBooks = arcs.map(([a, b]) => [bookOf(a), bookOf(b)]);
  const BUCKETS = [[8, .09, .55], [12, .14, .65], [20, .22, .8], [40, .34, 1]];
  const bucket = w => BUCKETS.reduce((k, b, i) => w >= b[0] ? i : k, 0);

  let W = 0, H = 0, PAD = 0, base = 0, progress = 1, book = -1;
  const xOf = ch => PAD + (ch + .5) / TOTAL * (W - 2 * PAD);

  function colours() {
    const cs = getComputedStyle(root);
    return { gold: cs.getPropertyValue('--gold').trim(), lit: cs.getPropertyValue('--gold-text').trim(),
             ink: cs.getPropertyValue('--ink').trim() };
  }
  function draw() {
    if (W < 40) return;   // hidden, or not laid out yet: nothing to draw
    const ctx = canvas.getContext('2d'), c = colours(), dpr = Math.min(devicePixelRatio || 1, 2);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const reach = PAD + progress * (W - 2 * PAD);
    // Arcs, batched by weight: one path per stroke style.
    for (let k = 0; k < BUCKETS.length; k++) {
      for (const lit of book < 0 ? [false] : [false, true]) {
        ctx.beginPath();
        arcs.forEach(([a, b, w], i) => {
          if (bucket(w) !== k) return;
          const on = book >= 0 && (arcBooks[i][0] === book || arcBooks[i][1] === book);
          if (on !== lit) return;
          const x1 = xOf(a), x2 = xOf(b), cx = (x1 + x2) / 2;
          if (cx > reach) return;
          ctx.moveTo(x2, base); ctx.arc(cx, base, (x2 - x1) / 2, 0, Math.PI, true);
        });
        const [, a, lw] = BUCKETS[k];
        ctx.strokeStyle = lit ? c.lit : c.gold;
        ctx.globalAlpha = lit ? Math.min(1, a * 2.6 + .1) : book >= 0 ? a * .35 : a;
        ctx.lineWidth = lit ? lw + .35 : lw;
        ctx.stroke();
      }
    }
    // The line of books: alternate shades, the chosen one in gold, a mark where the New Testament begins.
    ctx.globalAlpha = 1;
    for (let b = 0; b < 66; b++) {
      const x1 = xOf(start[b]) - (W - 2 * PAD) / TOTAL / 2, x2 = xOf(start[b] + X.chapters[b] - 1) + (W - 2 * PAD) / TOTAL / 2;
      ctx.fillStyle = b === book ? c.gold : c.ink;
      ctx.globalAlpha = b === book ? 1 : b % 2 ? .16 : .3;
      ctx.fillRect(x1, base + 3, x2 - x1, b === book ? 6 : 4);
    }
    ctx.globalAlpha = .55; ctx.fillStyle = c.gold;
    ctx.fillRect(xOf(start[39]) - 1, base + 12, 2, 8);
    ctx.globalAlpha = 1;
  }
  function size() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = canvas.clientWidth; PAD = 4; H = Math.round((W - 2 * PAD) / 2 + 24); base = H - 22;
    canvas.style.height = H + 'px';
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    draw();
  }
  function choose(b) {
    book = b;
    read.innerHTML = b < 0 ? '&nbsp;' : T(names[b], fmt.format(X.refs[b]), fmt.format(X.linked[b]));
    draw();
  }
  const bookAt = e => {
    const r = canvas.getBoundingClientRect();
    const ch = Math.floor((e.clientX - r.left - PAD) / (W - 2 * PAD) * TOTAL);
    return bookOf(Math.max(0, Math.min(TOTAL - 1, ch)));
  };
  canvas.addEventListener('pointermove', e => { if (e.pointerType === 'mouse') { const b = bookAt(e); if (b !== book) choose(b); } });
  canvas.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') choose(-1); });
  // On touch, press and slide: the book follows the finger.
  let dragging = false;
  canvas.addEventListener('pointerdown', e => {
    if (e.pointerType === 'mouse') return;
    dragging = true; choose(bookAt(e));
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* capture is a nicety */ }
  });
  canvas.addEventListener('pointermove', e => { if (dragging) { const b = bookAt(e); if (b !== book) choose(b); } });
  const stop = () => { dragging = false; };
  canvas.addEventListener('pointerup', stop); canvas.addEventListener('pointercancel', stop);
  canvas.addEventListener('keydown', e => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (step) { e.preventDefault(); choose(Math.max(0, Math.min(65, (book < 0 ? (step > 0 ? -1 : 66) : book) + step))); }
    else if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); choose(e.key === 'Home' ? 0 : 65); }
    else if (e.key === 'Escape') choose(-1);
  });
  canvas.addEventListener('blur', () => choose(-1));

  // The arcs are woven in, left to right, the first time the map is seen.
  function weave() {
    if (still.matches) { progress = 1; draw(); return; }
    const t0 = performance.now(), D = 1600;
    const ease = t => 1 - Math.pow(1 - t, 3);
    const tick = now => { progress = ease(Math.min(1, (now - t0) / D)); draw(); if (progress < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }
  size();
  if ('IntersectionObserver' in window && !still.matches) {
    progress = 0; draw();
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); weave(); } }, { threshold: .35 });
    io.observe(canvas);
  }
  let t = 0;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(size, 120); });
  // A new paper or theme repaints the gold.
  new MutationObserver(() => size()).observe(root, { attributes: true, attributeFilter: ['style', 'class', 'data-theme'] });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
})();
