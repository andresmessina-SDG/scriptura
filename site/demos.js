// The features, working: where the page would show a screenshot, it shows
// the thing itself, on real data (demos-data.js, built by
// tools/build-site.py --demos). Without the script the screenshots stay.
(() => {
  'use strict';
  const D = window.DEMOS;
  if (!D) return;
  const root = document.documentElement;
  const lang = ['es', 'ru'].includes(root.lang) ? root.lang : 'en';
  const [BY_FAMILY, BY_LINE, MARK, OT, NT, WFW, FREE] = D.ui[lang];
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  const el = (tag, cls, txt) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  };
  // Book names in the page's language, from the map's data (the app's own).
  const NAMES = window.XMAP && window.XMAP.names;
  const bookName = b => (NAMES && NAMES[lang][NAMES.en.indexOf(b)]) || b;
  const refName = r => { const m = r.match(/^(.*) (\d+:\d+)$/); return m ? `${bookName(m[1])} ${m[2]}` : r; };
  const band = key => {
    const img = document.querySelector(`.band img[src*="/${key}"]`);
    return img && img.closest('.band');
  };
  function mount(key, node, wide) {
    const b = band(key);
    if (!b) return;
    b.classList.add('live');
    if (wide) b.classList.add('wide');
    b.querySelector('.zoom').after(node);
  }
  function segmented(labels, onPick, label) {
    const g = el('div', 'seg');
    g.setAttribute('role', 'radiogroup');
    if (label) g.setAttribute('aria-label', label);
    labels.forEach((t, i) => {
      const b = el('button', null, t);
      b.type = 'button'; b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(i === 0));
      b.addEventListener('click', () => {
        g.querySelectorAll('button').forEach((x, j) => x.setAttribute('aria-checked', String(j === i)));
        onPick(i);
      });
      g.append(b);
    });
    return g;
  }

  // ── The Greek word by word ──
  (() => {
    const box = el('div', 'demo il');
    const eng = el('p', 'il-eng'); eng.lang = 'en';
    const words = el('ol', 'il-words');
    const parse = el('p', 'il-parse'); parse.setAttribute('aria-live', 'polite'); parse.lang = 'en';
    let pinned = null;
    function light(n) {
      box.querySelectorAll('[data-n]').forEach(x => x.classList.toggle('lit', !!n && x.dataset.n === n));
      const w = n && [...words.children].find(x => x.dataset.n === n);
      parse.textContent = w ? `${w.dataset.n} · ${w.dataset.p}` : ' ';
    }
    function show(key) {
      const v = D.inter[key];
      pinned = null;
      // Each page reads its own Bible above the words, as the app pairs the
      // interlinear with any Bible: the Reina-Valera 1909 carries Strong's
      // numbers, so its words light with the Greek and Hebrew; the Synodal
      // has none, so it only reads. Glosses and parsing are English, as in
      // the app, and marked so.
      const own = v[lang], line = own ? own.line : v.kjv;
      eng.lang = own ? lang : 'en';
      eng.replaceChildren(el('b', null, refName(v.ref) + ' '));
      line.forEach(([t, n]) => {
        if (!n) { eng.append(t); return; }
        const s = el('span', 'il-k', t); s.dataset.n = n.split(' ')[0]; eng.append(s);
      });
      words.dir = key === 'ot' ? 'rtl' : 'ltr';
      words.replaceChildren(...v.words.map(w => {
        const li = el('li', 'il-w');
        li.dataset.n = w.n; li.dataset.p = w.p; li.tabIndex = 0;
        const s = el('span', 'il-s', w.s); s.lang = key === 'ot' ? 'hbo' : 'grc';
        const t = el('span', 'il-t', w.t); t.dir = 'ltr';
        const g = el('span', 'il-g', w.g); g.dir = 'ltr'; g.lang = 'en';
        const n = el('span', 'il-n', w.n); n.dir = 'ltr';
        li.append(s, t, g, n);
        return li;
      }));
      light(null);
    }
    const over = e => { const t = e.target.closest('[data-n]'); if (t) light(t.dataset.n); };
    box.addEventListener('pointerover', over);
    box.addEventListener('focusin', over);
    box.addEventListener('pointerleave', () => light(pinned));
    box.addEventListener('click', e => { const t = e.target.closest('[data-n]'); if (t) { pinned = t.dataset.n; light(pinned); } });
    box.append(segmented([NT, OT], i => show(i ? 'ot' : 'nt')), eng, words, parse);
    show('nt');
    mount('interlinear', box);
  })();

  // ── Read the difference ──
  (() => {
    // The app's Read the difference is the English Bibles of the Family, in
    // every language: so is this, with its controls in the page's language.
    const R = D.diff, box = el('div', 'demo rd');
    let verse = 0, marking = false;
    const head = el('div', 'rd-head');
    const refs = segmented(R.refs.map(refName), i => { verse = i; fill(); });
    const mark = el('button', 'rd-mark', MARK);
    mark.type = 'button'; mark.setAttribute('aria-pressed', 'false');
    mark.addEventListener('click', () => { marking = !marking; mark.setAttribute('aria-pressed', String(marking)); box.classList.toggle('marking', marking); });
    head.append(refs, mark);
    // The Line: word for word at the left, free at the right. Open Bibles are
    // gold; the others are marked only by name, for their place.
    const line = el('div', 'rd-line');
    line.setAttribute('aria-hidden', 'true');
    line.append(el('span', 'rd-end l', WFW), el('span', 'rd-end r', FREE));
    R.others.forEach(o => { const m = el('span', 'rd-dot other', o.abbr); m.style.left = `${o.at * 100}%`; line.append(m); });
    R.bibles.forEach((b, i) => { const m = el('span', 'rd-dot', ''); m.style.left = `${Math.min(b.at, 1) * 100}%`; m.dataset.i = i; m.title = b.abbr; line.append(m); });
    const rows = el('ol', 'rd-rows'); rows.lang = 'en';
    const norm = w => w.toLowerCase().replace(/[^\p{L}\p{N}']/gu, '');
    // Word by word, in order, against the Bible above: the longest common
    // run keeps its order, so a moved word counts as a difference.
    function shared(a, b) {
      const A = a.map(norm), B = b.map(norm), m = A.length, n = B.length;
      const L = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));
      for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--)
        L[i][j] = A[i] && A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
      const keep = new Set();
      for (let i = 0, j = 0; i < m && j < n;) {
        if (A[i] && A[i] === B[j]) { keep.add(j); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) i++; else j++;
      }
      return keep;
    }
    function fill() {
      let above = null;
      rows.replaceChildren(...R.bibles.map((b, i) => {
        const li = el('li', 'rd-row'); li.dataset.i = i;
        const who = el('span', 'rd-who'); who.append(el('b', null, b.abbr), el('span', null, String(b.year)));
        who.title = b.name;
        const words = b.t[verse].split(/(\s+)/);
        const toks = words.filter(w => w.trim());
        const keep = above ? shared(above, toks) : new Set();
        const p = el('p', 'rd-text');
        let k = 0;
        words.forEach(w => {
          if (!w.trim()) { p.append(w); return; }
          const s = el('span', keep.has(k) ? 'same' : null, w); p.append(s); k++;
        });
        above = toks;
        li.append(who, p);
        return li;
      }));
    }
    const hl = i => box.querySelectorAll('[data-i]').forEach(x => x.classList.toggle('hot', x.dataset.i === i));
    box.addEventListener('pointerover', e => { const t = e.target.closest('[data-i]'); hl(t ? t.dataset.i : null); });
    box.addEventListener('pointerleave', () => hl(null));
    // The LSV's licence (CC BY-SA 4.0) asks for its copyright and source
    // wherever its text is shared; the verses here are its text unchanged.
    // Each Bible's licence, in the page's language; the LSV's (CC BY-SA 4.0)
    // asks for its copyright and source wherever its text is shared.
    const credit = el('p', 'rd-credit');
    credit.innerHTML = D.credit[lang];
    box.append(head, line, rows, credit);
    fill();
    mount('read.', box, true);
  })();

  // ── The Bible Family Tree ──
  (() => {
    const F = D.family, [L0, L1, , , AXIS] = F.lanes, W = F.w, H = F.h;
    const ZONES = D.zones[lang], UNFOLD = D.unfold[lang];
    const NS = 'http://www.w3.org/2000/svg';
    const sv = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; };
    const lineX = v => L0 + Math.min(Math.max(v, 0), 1) * (L1 - L0);
    const box = el('div', 'demo ft folded');
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' });
    svg.setAttribute('aria-label', band('family')?.querySelector('h3')?.textContent || '');
    const byId = Object.fromEntries(F.nodes.map(n => [n.id, n]));
    const parents = {};
    F.edges.forEach(e => (parents[e.t] = parents[e.t] || []).push(e.f));
    // The time axis, and (by literalness) the zone boundaries running down it.
    const axis = sv('g', { class: 'ft-axis' });
    F.ticks.forEach(([yr, y]) => { axis.append(sv('line', { x1: 40, x2: L1 + 40, y1: y, y2: y })); const t = sv('text', { x: 36, y: y + 4 }); t.textContent = yr; axis.append(t); });
    const guides = sv('g', { class: 'ft-guides' });
    [0, .33, .66, .9, 1].forEach(v => guides.append(sv('line', { x1: lineX(v), x2: lineX(v), y1: AXIS - 30, y2: H - 20 })));
    const edges = sv('g', { class: 'ft-edges' }), nodes = sv('g', { class: 'ft-nodes' });
    svg.append(guides, axis, edges, nodes);
    // The Line itself, pinned above the drawing while it scrolls by.
    const scale = el('div', 'ft-scale');
    scale.setAttribute('aria-hidden', 'true');
    scale.style.setProperty('--l', `${L0 / W * 100}%`); scale.style.setProperty('--r', `${(W - L1) / W * 100}%`);
    const track = el('div', 'ft-track');
    [[0, .33, ZONES[0]], [.33, .66, ZONES[1]], [.66, .9, ZONES[2]], [.9, 1, ZONES[3]]].forEach(([a, b, t], i) => {
      const z = el('span', 'ft-zone z' + i, t); z.style.left = `${a * 100}%`; z.style.width = `${(b - a) * 100}%`; track.append(z);
    });
    scale.append(track);
    const notes = el('div', 'ft-notes');
    (F.notes[lang] || F.notes.en).forEach(([y, t]) => { const p = el('p', 'ft-note', t); p.style.top = `${y / H * 100}%`; p.dataset.y = y; notes.append(p); });
    const card = el('div', 'ft-card'); card.hidden = true;
    const paths = F.edges.map(e => { const p = sv('path', { class: `ft-e ${e.k}` }); p.dataset.f = e.f; p.dataset.t = e.t; edges.append(p); return p; });
    const marks = F.nodes.map(n => {
      const g = sv('g', { class: 'ft-n' + (n.root ? ' root' : ''), tabindex: 0 }); g.dataset.id = n.id;
      g.append(sv('circle', { r: 5 }));
      const t = sv('text', { y: 4 }); t.textContent = n.abbr; g.append(t);
      nodes.append(g); return g;
    });
    // The curve leaves the parent straight down (family_layout.edge_curve).
    const curve = (a, b) => {
      if (Math.abs(b[1] - a[1]) < 30) { const dip = Math.max(a[1], b[1]) + 34; return `M${a}C${a[0]},${dip} ${b[0]},${dip} ${b}`; }
      const mid = (a[1] + b[1]) / 2; return `M${a}C${a[0]},${mid} ${b[0]},${mid} ${b}`;
    };
    let pos = Object.fromEntries(F.nodes.map(n => [n.id, n.xy]));
    function place() {
      F.nodes.forEach((n, i) => {
        const [x, y] = pos[n.id], left = x > 700 && !n.root;
        marks[i].setAttribute('transform', `translate(${x},${y})`);
        const t = marks[i].querySelector('text');
        t.setAttribute('x', left ? -10 : 10); t.setAttribute('text-anchor', left ? 'end' : 'start');
      });
      paths.forEach(p => p.setAttribute('d', curve(pos[p.dataset.f], pos[p.dataset.t])));
    }
    // Rearranging slides each Bible sideways; time stays put.
    let anim = 0;
    function arrange(line) {
      const from = pos, to = Object.fromEntries(F.nodes.map(n => [n.id, line ? n.xyl : n.xy]));
      box.classList.toggle('by-line', line);
      box.classList.add('all-in');
      cancelAnimationFrame(anim);
      if (still.matches) { pos = to; place(); return; }
      const t0 = performance.now(), Dur = 650, ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      const step = now => {
        const k = ease(Math.min(1, (now - t0) / Dur));
        pos = Object.fromEntries(F.nodes.map(n => [n.id, [from[n.id][0] + (to[n.id][0] - from[n.id][0]) * k, to[n.id][1]]]));
        place();
        if (k < 1) anim = requestAnimationFrame(step);
      };
      anim = requestAnimationFrame(step);
    }
    // A Bible and everything it came from; its card says where it sits on the Line.
    function lineage(id, out = new Set()) { out.add(id); (parents[id] || []).forEach(p => lineage(p, out)); return out; }
    function focus(id) {
      const set = id ? lineage(id) : null;
      box.classList.toggle('tracing', !!id);
      marks.forEach(m => m.classList.toggle('on', !!set && set.has(m.dataset.id)));
      paths.forEach(p => p.classList.toggle('on', !!set && set.has(p.dataset.t) && set.has(p.dataset.f)));
      if (!id) { card.hidden = true; return; }
      const n = byId[id];
      card.replaceChildren(el('b', null, n.name), el('span', null, (D.yl[lang] || []).reduce((s, [a, b]) => s.split(a).join(b), n.yl)));
      if (n.at != null) {
        const z = n.at < .33 ? 0 : n.at < .66 ? 1 : n.at < .9 ? 2 : 3;
        const bar = el('span', 'ft-bar'); const dot = el('i'); dot.style.left = `${Math.min(n.at, 1) * 100}%`; bar.append(dot);
        card.append(bar, el('span', 'ft-zone-name', ZONES[z]));
      }
      if (n.note) { const p = el('p', null, n.note); p.lang = 'en'; card.append(p); }
      card.hidden = false;
      const [x, y] = pos[id];
      card.style.left = `${Math.min(x / W * 100, 62)}%`;
      card.style.top = `calc(${y / H * 100}% + 14px)`;
    }
    svg.addEventListener('pointerover', e => { const g = e.target.closest('.ft-n'); if (g) focus(g.dataset.id); });
    svg.addEventListener('pointerleave', () => focus(null));
    svg.addEventListener('focusin', e => { const g = e.target.closest('.ft-n'); if (g) focus(g.dataset.id); });
    svg.addEventListener('focusout', () => focus(null));
    // Drawn down the page in time: each line traces itself as the reader
    // scrolls to its year.
    // The sheet sits in a frame that scrolls sideways on a phone; on a wide
    // screen the frame is not a scroller, so the Line above still pins.
    const stage = el('div', 'ft-stage'), scroll = el('div', 'ft-scroll');
    const sheet = el('div', 'ft-sheet');
    sheet.append(svg, notes, card);
    scroll.append(scale, sheet);
    stage.append(scroll);
    function reveal() {
      const r = svg.getBoundingClientRect(), shown = Math.min(innerHeight * .85, stage.getBoundingClientRect().bottom);
      const upto = (shown - r.top) / r.height * H;
      paths.forEach(p => { if (!p.classList.contains('in') && pos[p.dataset.t][1] < upto) p.classList.add('in'); });
      marks.forEach(m => { if (!m.classList.contains('in') && pos[m.dataset.id][1] < upto) m.classList.add('in'); });
      notes.querySelectorAll('.ft-note').forEach(n => { if (+n.dataset.y < upto) n.classList.add('in'); });
    }
    let ticking = false;
    const onScroll = () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { ticking = false; reveal(); }); } };
    place();
    paths.forEach(p => { const L = p.getTotalLength ? Math.ceil(p.getTotalLength()) + 2 : 2000; p.style.setProperty('--len', L); });
    if (still.matches) box.classList.add('all-in');
    else addEventListener('scroll', onScroll, { passive: true });

    // Folded, it shows the tree before 1611 and the King James, then fades:
    // the button unfolds the four centuries after it.
    const TEASE = 0.31;   // of the drawing: down to just past 1611
    const veil = el('div', 'ft-veil');
    const open = el('button', 'ft-open');
    open.type = 'button'; open.setAttribute('aria-expanded', 'false');
    open.innerHTML = `<span>${UNFOLD[0]}</span><em>${UNFOLD[1]}</em><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6.5 4 4 4-4"/></svg>`;
    veil.append(open);
    stage.append(veil);
    const fold = el('button', 'ft-fold', UNFOLD[2]); fold.type = 'button';
    const teaseH = () => Math.round(sheet.getBoundingClientRect().width * H / W * TEASE);
    const sizeFolded = () => { if (box.classList.contains('folded')) stage.style.height = `${teaseH()}px`; };
    // Folded, the Bibles under the veil are out of the tab order too.
    const tabs = folded => marks.forEach((m, i) => m.setAttribute('tabindex', folded && F.nodes[i].xy[1] > H * TEASE * .8 ? -1 : 0));
    function setOpen(on) {
      tabs(!on);
      const from = stage.getBoundingClientRect().height;
      box.classList.toggle('folded', !on);
      open.setAttribute('aria-expanded', String(on));
      stage.style.height = on ? 'auto' : `${teaseH()}px`;
      const to = stage.getBoundingClientRect().height;
      if (!still.matches) {
        stage.classList.add('moving');
        const dur = on ? 900 : 500;
        stage.animate([{ height: `${from}px` }, { height: `${to}px` }], { duration: dur, easing: 'cubic-bezier(0.77, 0, 0.175, 1)' });
        setTimeout(() => stage.classList.remove('moving'), dur + 30);
      }
      if (on) { reveal(); setTimeout(reveal, 450); setTimeout(reveal, 950); }
      else band('family')?.scrollIntoView({ block: 'start', behavior: still.matches ? 'auto' : 'smooth' });
    }
    open.addEventListener('click', () => setOpen(true));
    fold.addEventListener('click', () => setOpen(false));
    addEventListener('resize', sizeFolded);
    const pick = segmented([BY_FAMILY, BY_LINE], i => arrange(i === 1));
    pick.classList.add('ft-pick');
    box.append(pick, el('p', 'ft-swipe', D.swipe[lang]), stage, fold);
    mount('family', box, true);
    sizeFolded();
    tabs(true);
    if (!still.matches) {
      const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); reveal(); } }, { threshold: .2 });
      io.observe(stage);
    }
  })();

  // ── Art for the passage you are reading ──
  (() => {
    const A = D.art, box = el('div', 'demo art');
    const frame = el('div', 'art-frame');
    const imgs = A.map((a, i) => {
      const im = el('img'); im.src = (document.querySelector('script[src*="demos.js"]').src.replace(/demos\.js.*$/, '')) + 'art/' + a.img;
      im.alt = `${a.title}, ${a.artist}, ${a.year}`; im.width = a.w; im.height = a.h; im.loading = i ? 'lazy' : 'eager';
      if (i) im.classList.add('off');
      frame.append(im); return im;
    });
    const verse = el('blockquote', 'art-verse');
    const cap = el('p', 'art-cap'); cap.lang = 'en';
    function show(i) {
      imgs.forEach((im, j) => im.classList.toggle('off', j !== i));
      const a = A[i];
      verse.replaceChildren(el('b', null, refName(`${a.ref[0]} ${a.ref[1]}:${a.ref[2]}`) + ' '), a.t[lang] || a.t.en);
      const id = a.img.replace(/\D/g, ''), T2 = D.arttitles[id] && D.arttitles[id][lang];
      cap.textContent = `${T2 || a.title} · ${(D.artists[lang] || {})[a.artist] || a.artist}, ${a.year} · ${D.pd[lang]}`;
      cap.lang = T2 || lang === 'en' ? lang : 'en';
    }
    box.append(frame, segmented(A.map(a => refName(`${a.ref[0]} ${a.ref[1]}:${a.ref[2]}`)), show), verse, cap);
    show(0);
    mount('art', box);
  })();
})();
