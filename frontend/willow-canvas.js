/* willow-canvas.js — Claude-optimized willow tree geometry + canvas renderer
 * Adapted from claude-willow-ref.html for 让果子熟 forest SPA.
 * Deterministic RNG seed 20261013; data strands re-layout when idea.branches change.
 */
(function (global) {
'use strict';

/* ========= 柳树几何：树干 → 拱形主枝 → 小枝 → 下垂柳条（装饰枝 + 数据枝）→ 柳叶 ========= */
function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function cubic(p0, p1, p2, p3, t) { const u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t; return { x: a * p0.x + b * p1.x + c * p2.x + d * p3.x, y: a * p0.y + b * p1.y + c * p2.y + d * p3.y }; }
function sampleCubic(p0, p1, p2, p3, n) { const a = []; for (let i = 0; i <= n; i++) a.push(cubic(p0, p1, p2, p3, i / n)); return a; }
function arcLen(pts) { let L = 0; for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y); return L; }
function tangentAt(pts, i) { const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)]; const dx = b.x - a.x, dy = b.y - a.y, m = Math.hypot(dx, dy) || 1; return { x: dx / m, y: dy / m }; }

/* 一根下垂的柳条：先顺着枝的方向伸出，再被"重力"慢慢拉直往下 —— 喷泉形弧线 */
function hang(x, y, dx, dy, L, k, seg, wob, wph) {
  const N = Math.max(3, Math.round(L / seg)), s = L / N;
  const p = new Float32Array((N + 1) * 2);
  let px = x, py = y, vx = dx, vy = dy;
  p[0] = px; p[1] = py;
  for (let i = 1; i <= N; i++) {
    vy += k * s; const m = Math.hypot(vx, vy); vx /= m; vy /= m;
    px += vx * s; py += vy * s; p[2 * i] = px; p[2 * i + 1] = py;
  }
  if (wob) for (let i = 1; i <= N; i++) { const u = i / N; p[2 * i] += wob * Math.sin(u * Math.PI * 1.25 + wph) * u; }
  const wt = new Float32Array(N + 1);
  for (let i = 0; i <= N; i++) wt[i] = Math.pow(i / N, 1.35);
  return { rest: p, wt, N, seg: s, L };
}

/* 沿柳条生成叶子：狭长、交错、向下斜挂 */
function makeLeaves(st, rnd, size, avoid) {
  const out = [];
  let s = 4 + rnd() * 4, side = rnd() < 0.5 ? -1 : 1;
  while (s < st.L - 1.5) {
    const u = s / st.L;
    let ok = true;
    if (avoid) for (const a of avoid) if (Math.abs(s - a) < 11) { ok = false; break; }
    if (ok) {
      const pos = s / st.seg, k = Math.min(st.N - 1, Math.floor(pos)), f = pos - k;
      const len = (6.5 + rnd() * 5.5) * (1 - 0.5 * u) * size;
      out.push({ s, k, f, side, ang: 0.28 + rnd() * 0.42, len, wid: (1.5 + rnd() * 1.1) * size, c: (rnd() * 4) | 0 });
    }
    s += 3.6 + rnd() * 3.4; side = -side;
  }
  return out;
}

function buildTree(W, H, idea) {
  const rnd = mulberry32(20261013);
  const narrow = W < 560;
  const gH = Math.round(Math.max(58, Math.min(86, H * 0.12)));
  const groundY = H - gH;
  const cx = W * 0.5;
  const R = narrow ? W * 0.52 : Math.min(W * 0.47, 620);
  const topY = Math.max(26, H * 0.06);
  const trunkH = (groundY - topY) * (narrow ? 0.26 : 0.3);
  const forkY = groundY - trunkH;
  const crownH = forkY - topY;
  const domeEdge = topY + crownH * 0.66;
  const domeY = x => { const u = Math.min(1, Math.abs(x - cx) / R); return topY + (domeEdge - topY) * u * u; };
  const baseW = Math.max(16, Math.min(46, R * 0.11));
  const topW = baseW * 0.7;
  const base = { x: cx - baseW * 0.12, y: groundY + 6 };
  const fork = { x: cx + R * 0.02, y: forkY };

  /* 树干：短而粗，带 S 形弯曲、根部外扩、向上收分 */
  const TN = 28;
  const tPts = sampleCubic(base, { x: base.x - baseW * 0.55, y: groundY - trunkH * 0.4 }, { x: fork.x + baseW * 0.5, y: groundY - trunkH * 0.76 }, fork, TN);
  const tWs = tPts.map((_, i) => { const u = i / TN; return topW + (baseW - topW) * Math.pow(1 - u, 1.4) + baseW * 0.55 * Math.exp(-u * 12); });

  /* 分叉：树干顶部分成 2~3 根粗枝，斜向上伸展（不再从一个点放射） */
  const nS = narrow ? 2 : 3;
  const angs = nS === 3 ? [-0.66, 0.04, 0.64] : [-0.36, 0.34];
  const stems = angs.map((a0, j) => {
    const a = a0 + (rnd() - 0.5) * 0.1;
    const len = crownH * (nS === 3 ? (j === 1 ? 0.46 : 0.38) : 0.5) * (0.94 + rnd() * 0.12);
    const s = { x: fork.x + (j - (nS - 1) / 2) * topW * 0.34, y: forkY + 8 };
    const e = { x: s.x + Math.sin(a) * len * 1.2, y: s.y - Math.cos(a) * len };
    const dx = e.x - s.x, dy = e.y - s.y;
    const pts = sampleCubic(s, { x: s.x + dx * 0.08, y: s.y + dy * 0.45 }, { x: s.x + dx * 0.62, y: s.y + dy * 0.86 }, e, 20);
    const w0 = topW * (nS === 3 ? (j === 1 ? 0.58 : 0.52) : 0.66);
    return { pts, ws: pts.map((_, k) => w0 * (1 - 0.42 * k / 20)), b: 0 };
  });

  /* 主枝：从粗枝上段分出，先拱起再向外弯垂，枝梢落在树冠穹顶上 */
  const nL = narrow ? 4 : 7;
  const byStem = stems.map(() => []);
  for (let i = 0; i < nL; i++) {
    const u = -1 + 2 * (i + 0.5) / nL + (rnd() - 0.5) * 0.08, ex = cx + R * 0.88 * u;
    let best = 0, bd = 1e9; stems.forEach((S, j) => { const d = Math.abs(S.pts[20].x - ex); if (d < bd) { bd = d; best = j; } });
    byStem[best].push(u);
  }
  const limbs = [];
  byStem.forEach((us, j) => {
    const S = stems[j], sx0 = S.pts[20].x;
    us.sort((a, b) => Math.abs(cx + R * 0.88 * a - sx0) - Math.abs(cx + R * 0.88 * b - sx0));
    us.forEach((u, rank) => {
      const au = Math.abs(u), ex = cx + R * 0.88 * u, ey = domeY(ex) + 4 + rnd() * 10;
      const idx = Math.max(8, 20 - rank * 4), sp = S.pts[idx], sx = sp.x, sy = sp.y, dx = ex - sx;
      const c1 = { x: sx + dx * 0.12, y: sy - Math.max(14, (sy - ey) * 0.8) - 16 };
      const c2 = { x: ex - dx * 0.42, y: Math.max(topY * 0.45, ey - (sy - topY) * 0.2 - 12) };
      const LN = 30, pts = sampleCubic({ x: sx, y: sy }, c1, c2, { x: ex, y: ey }, LN);
      const w0 = S.ws[idx] * 0.72;
      limbs.push({ pts, ws: pts.map((_, k) => w0 * Math.pow(1 - k / LN, 1.1) + 1.1), b: 0.03 + au * 0.15, u });
    });
  });
  /* 小枝：从主枝外半段分出，向外上方伸，再弯下 */
  const twigs = [];
  for (const L of limbs) {
    const n = 2 + (rnd() < 0.55 ? 1 : 0);
    for (let j = 0; j < n; j++) {
      const t = 0.36 + rnd() * 0.46, idx = Math.round(t * (L.pts.length - 1));
      const p = L.pts[idx], tg = tangentAt(L.pts, idx);
      const side = j % 2 ? -1 : 1, a = side * (0.4 + rnd() * 0.5);
      let dx = tg.x * Math.cos(a) - tg.y * Math.sin(a), dy = tg.x * Math.sin(a) + tg.y * Math.cos(a);
      if (dy > 0.1) dy = -0.3;
      const m = Math.hypot(dx, dy); dx /= m; dy /= m;
      const len = R * (0.14 + rnd() * 0.14);
      const e = { x: p.x + dx * len, y: Math.max(topY * 0.7, p.y + dy * len + len * 0.3) };
      if (Math.abs(e.x - cx) > R * 0.99) e.x = cx + Math.sign(e.x - cx) * R * 0.99;
      const c1 = { x: p.x + dx * len * 0.45, y: p.y + dy * len * 0.45 - len * 0.12 };
      const c2 = { x: e.x - dx * len * 0.22, y: e.y - len * 0.22 };
      const pts = sampleCubic(p, c1, c2, e, 16);
      const w0 = L.ws[idx] * 0.5;
      twigs.push({ pts, ws: pts.map((_, k) => w0 * (1 - k / 16) + 0.75), b: L.b + 0.08 + t * 0.12 });
    }
  }

  /* 数据枝的挂点：按创建顺序从左到右均匀分布，挂在离目标最近、尽量高的枝上 */
  const nB = idea.branches.length;
  const cand = [];
  for (const L of limbs) for (let k = 12; k < L.pts.length; k++) cand.push({ p: L.pts[k], tg: tangentAt(L.pts, k) });
  for (const T of twigs) for (let k = 5; k < T.pts.length; k++) cand.push({ p: T.pts[k], tg: tangentAt(T.pts, k) });
  const order = idea.branches.map((b, i) => i).sort((a, b) => idea.branches[a].c - idea.branches[b].c);
  const spanX = narrow ? Math.min(R * 0.86, W / 2 - 24) : R * 0.88;
  const band = narrow ? 0 : baseW * 0.8 + 30, nLf = Math.floor(nB / 2), nRt = nB - nLf;
  const slotX = k => band === 0 || nLf === 0 ? cx + spanX * (-1 + 2 * (k + 0.5) / nB)
    : k < nLf ? cx - spanX + (spanX - band) * (k + 0.5) / nLf : cx + band + (spanX - band) * (k - nLf + 0.5) / nRt;
  const used = [];
  const gapMax = Math.max(40, Math.min(66, H * 0.085));
  const s0 = 30;
  const dataStrands = new Array(nB);
  order.forEach((bi, slot) => {
    const tx = slotX(slot);
    let best = null, bs = 1e9;
    for (const c of cand) {
      if (used.some(x => Math.abs(x - c.p.x) < 26)) continue;
      const sc = Math.abs(c.p.x - tx) * 1.0 + (c.p.y - topY) * 0.22;
      if (sc < bs) { bs = sc; best = c; }
    }
    used.push(best.p.x);
    const b = idea.branches[bi];
    const m = Math.max(1, b.steps.length);
    const hasFruit = !!b.fruit && b.dropped == null;
    const tail = hasFruit ? 0.8 : 0;
    const avail = groundY - 18 - best.p.y - s0 - (hasFruit ? 30 : 10);
    const gap = Math.max(22, Math.min(gapMax, avail / Math.max(0.6, m - 1 + tail)));
    const nodeS = []; for (let j = 0; j < b.steps.length; j++) nodeS.push(s0 + j * gap);
    const lastS = nodeS.length ? nodeS[nodeS.length - 1] : s0;
    const fruitS = hasFruit ? lastS + gap * 0.8 : null;
    const L = hasFruit ? fruitS : lastS + 14;
    let dx = best.tg.x * 0.55, dy = -0.12; const mm = Math.hypot(dx, dy); dx /= mm; dy /= mm;
    const st = hang(best.p.x, best.p.y, dx, dy, L, 0.06, 6, 4 + rnd() * 3, rnd() * 6);
    st.layer = 2; st.bi = bi; st.slot = slot; st.nodeS = nodeS; st.fruitS = fruitS; st.gap = gap;
    st.amp = 3 + rnd() * 1.5; st.fr = 0.55 + rnd() * 0.25; st.ph = rnd() * 6.28; st.b = 0;
    st.leaves = makeLeaves(st, rnd, 1.0, hasFruit ? nodeS.concat([fruitS]) : nodeS);
    dataStrands[bi] = st;
  });

  /* 装饰柳条：主枝、小枝外半段上密密挂下来；数据枝附近的放到后层，保证节点清楚 */
  const strands = [];
  const dataX = dataStrands.map(d => d.rest[0]);
  const addFrom = (pts, t0, step, lenK = 1, t1 = 1, back = false) => {
    const total = arcLen(pts);
    let acc = 0, next = total * t0;
    for (let k = 1; k < pts.length; k++) {
      const segL = Math.hypot(pts[k].x - pts[k - 1].x, pts[k].y - pts[k - 1].y);
      acc += segL;
      while (acc >= next && next <= total * t1) {
        if (rnd() < 0.76) {
          const p = pts[k], tg = tangentAt(pts, k);
          let dx = tg.x * 0.9, dy = Math.max(-0.55, tg.y * 0.9 - 0.35); const m = Math.hypot(dx, dy); dx /= m; dy /= m;
          const off = Math.abs(p.x - cx) / R;
          const room = groundY - 14 - p.y;
          const L = room * (0.45 + 0.5 * Math.pow(rnd(), 0.6)) * (0.6 + 0.4 * off) * lenK;
          let layer = back || rnd() < 0.5 ? 0 : 1;
          if (dataX.some(x => Math.abs(x - p.x) < 22)) layer = 0;
          if (Math.abs(p.x - cx) < baseW * 1.6) layer = 0;
          const st = hang(p.x, p.y, dx, dy, Math.max(30, L), 0.018 + rnd() * 0.02, 9, 3 + rnd() * 6, rnd() * 6);
          st.layer = layer; st.amp = (2.5 + rnd() * 4.5) * Math.min(1.4, st.L / 260); st.fr = 0.5 + rnd() * 0.45; st.ph = rnd() * 6.28;
          st.b = 0.08 + 0.6 * Math.pow(rnd(), 1.4) * (0.5 + 0.5 * off);
          st.leaves = makeLeaves(st, rnd, layer ? 1 : 0.85, null);
          strands.push(st);
        }
        next += step * (0.8 + rnd() * 0.5);
      }
    }
  };
  const step = narrow ? 11 : 13;
  for (const L of limbs) addFrom(L.pts, 0.34, step);
  for (const T of twigs) addFrom(T.pts, 0.2, step);
  /* 树冠内侧补一些短柳条，让树冠饱满，不露出光秃的枝骨 */
  for (const L of limbs) addFrom(L.pts, 0.08, step * 1.15, 0.5, 0.34, false);
  for (const S of stems) addFrom(S.pts, 0.45, step * 1.4, 0.42, 1, false);
  /* 后层薄雾：一层淡色长柳条垫在枝干后面，让树冠有纵深 */
  for (const L of limbs) addFrom(L.pts, 0.18, step * 1.1, 0.9, 1, true);

  /* 所有柳条共用一块缓冲区，每帧把风摆后的坐标写进去 */
  const all = strands.concat(dataStrands);
  let off = 0; for (const s of all) { s.off = off; off += (s.N + 1) * 2; }
  const buf = new Float32Array(off);
  for (const s of all) buf.set(s.rest, s.off);

  return { W, H, groundY, gH, cx, R, topY, forkY, base: { x: cx - baseW * 0.12, y: groundY }, trunk: { pts: tPts, ws: tWs }, baseW, stems, limbs, twigs, strands, dataStrands, all, buf };
}

/* 柳条上弧长 s 处的当前坐标（已含风摆） */
function strandPoint(tree, st, s) {
  const pos = Math.max(0, Math.min(st.N, s / st.seg)), k = Math.min(st.N - 1, Math.floor(pos)), f = pos - k, o = st.off + k * 2, b = tree.buf;
  return { x: b[o] + (b[o + 2] - b[o]) * f, y: b[o + 1] + (b[o + 3] - b[o + 1]) * f };
}
function strandRestPoint(st, s) {
  const pos = Math.max(0, Math.min(st.N, s / st.seg)), k = Math.min(st.N - 1, Math.floor(pos)), f = pos - k, r = st.rest;
  return { x: r[k * 2] + (r[k * 2 + 2] - r[k * 2]) * f, y: r[k * 2 + 1] + (r[k * 2 + 3] - r[k * 2 + 1]) * f };
}

/* ========= Canvas 绘制：远山在 SVG，树和柳条在 Canvas，节点和文字在 HTML 层 ========= */
const RD = { tok: null, buckets: null, grass: null };

function readTokens() {
  const cs = getComputedStyle(document.documentElement), g = n => cs.getPropertyValue(n).trim();
  RD.tok = {
    bark: g('--bark'), barkHi: g('--bark-hi'), barkLo: g('--bark-lo'),
    stem: g('--stem'), stemBack: g('--stem-back'), stemStrong: g('--stem-strong'),
    leaf: [g('--leaf-1'), g('--leaf-2'), g('--leaf-3'), g('--leaf-4')],
    leafBack: [g('--leaf-back-1'), g('--leaf-back-2')],
    dry: g('--dry'), dryLeaf: g('--dry-leaf'),
    ground: g('--ground'), ground2: g('--ground-2'), grass: g('--grass'),
    hillFar: g('--hill-far'), hillNear: g('--hill-near')
  };
}

function prepRender(tree) {
  const back = [[], []], front = [[], [], [], []];
  for (const st of tree.strands) for (const lf of st.leaves) {
    const a = lf.side * lf.ang; lf.ca = Math.cos(a); lf.sa = Math.sin(a); lf.st = st;
    if (st.layer === 0) back[lf.c & 1].push(lf); else front[lf.c].push(lf);
  }
  for (const st of tree.dataStrands) for (const lf of st.leaves) { const a = lf.side * lf.ang; lf.ca = Math.cos(a); lf.sa = Math.sin(a); lf.st = st; }
  RD.buckets = { back, front };
  /* 草叶 */
  const rnd = mulberry32(77), gr = [];
  for (let x = -4; x < tree.W + 4; x += 3.2 + rnd() * 3) gr.push({ x, h: 3 + rnd() * 7 * (0.5 + 0.5 * Math.sin(x * 0.02) ** 2), lean: (rnd() - 0.5) * 2.4, ph: rnd() * 6 });
  RD.grass = gr;
}

/* 风：每根柳条按弧长加权摆动，越靠近梢部摆得越大，并带一点沿枝传递的相位差 */
function sway(tree, t, amp, dataK) {
  const b = tree.buf;
  const gust = 0.72 + 0.22 * Math.sin(t * 0.37) + 0.12 * Math.sin(t * 1.13 + 2);
  for (const st of tree.all) {
    const A = amp * st.amp * gust * (st.layer === 2 ? dataK : st.layer === 0 ? 0.8 : 1);
    const o = st.off, r = st.rest, w = st.wt, N = st.N;
    if (A === 0) { b.set(r, o); continue; }
    const base = t * st.fr + st.ph;
    for (let i = 0; i <= N; i++) {
      const ph = base - (i / N) * 2.3;
      const dx = A * w[i] * (Math.sin(ph) + 0.32 * Math.sin(ph * 2.3 + 1.1) + 0.3);
      b[o + 2 * i] = r[2 * i] + dx;
      b[o + 2 * i + 1] = r[2 * i + 1] - Math.abs(dx) * 0.07 * w[i];
    }
  }
}

/* 收分的枝干轮廓（可只画前 frac 段，用于生长动画） */
function taperPath(ctx, pts, ws, frac) {
  const n = pts.length - 1, lim = Math.max(0.0001, Math.min(1, frac)) * n, k = Math.floor(lim);
  const P = [], Wd = [];
  for (let i = 0; i <= Math.min(n, k); i++) { P.push(pts[i]); Wd.push(ws[i]); }
  if (k < n && lim > k) { const f = lim - k, a = pts[k], b = pts[k + 1]; P.push({ x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }); Wd.push(ws[k] + (ws[k + 1] - ws[k]) * f); }
  if (P.length < 2) return false;
  const L = [], R = [];
  for (let i = 0; i < P.length; i++) {
    const a = P[Math.max(0, i - 1)], b = P[Math.min(P.length - 1, i + 1)];
    let tx = b.x - a.x, ty = b.y - a.y; const m = Math.hypot(tx, ty) || 1; tx /= m; ty /= m;
    const h = Wd[i] / 2;
    L.push([P[i].x - ty * h, P[i].y + tx * h]); R.push([P[i].x + ty * h, P[i].y - tx * h]);
  }
  ctx.moveTo(L[0][0], L[0][1]);
  for (let i = 1; i < L.length; i++) ctx.lineTo(L[i][0], L[i][1]);
  for (let i = R.length - 1; i >= 0; i--) ctx.lineTo(R[i][0], R[i][1]);
  ctx.closePath();
  return true;
}

function leafPath(ctx, tree, lf, g) {
  const st = lf.st, b = tree.buf, o = st.off + lf.k * 2;
  const x0 = b[o], y0 = b[o + 1], x1 = b[o + 2], y1 = b[o + 3];
  const px = x0 + (x1 - x0) * lf.f, py = y0 + (y1 - y0) * lf.f;
  let dx = x1 - x0, dy = y1 - y0; const m = Math.hypot(dx, dy) || 1; dx /= m; dy /= m;
  const lx = dx * lf.ca - dy * lf.sa, ly = dx * lf.sa + dy * lf.ca;
  const len = lf.len * g, wid = lf.wid * g;
  const tx = px + lx * len, ty = py + ly * len, mx = px + lx * len * 0.45, my = py + ly * len * 0.45, nx = -ly * wid, ny = lx * wid;
  ctx.moveTo(px, py); ctx.quadraticCurveTo(mx + nx, my + ny, tx, ty); ctx.quadraticCurveTo(mx - nx, my - ny, px, py);
}

function stemPath(ctx, tree, st, upto) {
  const b = tree.buf, o = st.off, N = st.N, lim = Math.min(N, upto / st.seg), k = Math.floor(lim);
  ctx.moveTo(b[o], b[o + 1]);
  for (let i = 1; i <= k; i++) ctx.lineTo(b[o + 2 * i], b[o + 2 * i + 1]);
  if (k < N && lim > k) { const f = lim - k, q = o + 2 * k; ctx.lineTo(b[q] + (b[q + 2] - b[q]) * f, b[q + 1] + (b[q + 3] - b[q + 1]) * f); }
}

/* 一帧：G=装饰生长量，S=整体缩放（树苗→大树），dv=每根数据枝的可见长度/叶量/焦点 */
function drawScene(ctx, tree, o) {
  const T = RD.tok, { G, S, t, dv, focus, dpr } = o;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, tree.W, tree.H);
  const bx = tree.base.x, by = tree.base.y;
  if (S > 0.001) {
    ctx.save();
    ctx.translate(bx, by); ctx.scale(S, S); ctx.translate(-bx, -by);
    const lw = w => Math.max(w, 0.7 / S);
    for (const st of tree.strands) st.vis = Math.max(0, Math.min(1, (G - st.b) / 0.3));

    /* 后层柳条：淡、细，像隔着一层薄雾 */
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = T.stemBack; ctx.lineWidth = lw(0.9); ctx.beginPath();
    for (const st of tree.strands) if (st.layer === 0 && st.vis > 0) stemPath(ctx, tree, st, st.vis * st.L);
    ctx.stroke();
    ctx.globalAlpha = 0.85;
    RD.buckets.back.forEach((arr, ci) => {
      ctx.fillStyle = T.leafBack[ci]; ctx.beginPath();
      for (const lf of arr) { const v = lf.st.vis * lf.st.L; if (lf.s > v) continue; leafPath(ctx, tree, lf, Math.min(1, Math.max(0.3, (v - lf.s) / 22))); }
      ctx.fill();
    });
    ctx.globalAlpha = 1;

    /* 枝干 */
    ctx.fillStyle = T.bark;
    ctx.beginPath();
    for (const St of tree.stems) taperPath(ctx, St.pts, St.ws, G / 0.2);
    for (const L of tree.limbs) taperPath(ctx, L.pts, L.ws, (G - L.b) / 0.28);
    ctx.fill();
    ctx.fillStyle = T.barkHi; ctx.beginPath();
    for (const W of tree.twigs) taperPath(ctx, W.pts, W.ws, (G - W.b) / 0.3);
    ctx.fill();
    const tg = ctx.createLinearGradient(bx - tree.baseW * 1.1, 0, bx + tree.baseW * 1.1, 0);
    tg.addColorStop(0, T.barkHi); tg.addColorStop(0.45, T.bark); tg.addColorStop(1, T.barkLo);
    ctx.fillStyle = tg; ctx.beginPath(); taperPath(ctx, tree.trunk.pts, tree.trunk.ws, 1); ctx.fill();
    /* 树皮纹 */
    ctx.strokeStyle = T.barkLo; ctx.globalAlpha = 0.38; ctx.lineWidth = lw(1);
    const tp = tree.trunk.pts, tw = tree.trunk.ws;
    for (const f of [-0.28, -0.04, 0.22]) {
      ctx.beginPath();
      for (let i = 2; i < tp.length - 2; i++) {
        const a = tp[i - 1], c = tp[i + 1]; let tx = c.x - a.x, ty = c.y - a.y; const m = Math.hypot(tx, ty) || 1; tx /= m; ty /= m;
        const off = tw[i] * (f + 0.05 * Math.sin(i * 1.7 + f * 9));
        const x = tp[i].x - ty * off, y = tp[i].y + tx * off;
        i === 2 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    /* 前层柳条 */
    ctx.strokeStyle = T.stem; ctx.lineWidth = lw(1.05); ctx.beginPath();
    for (const st of tree.strands) if (st.layer === 1 && st.vis > 0) stemPath(ctx, tree, st, st.vis * st.L);
    ctx.stroke();
    RD.buckets.front.forEach((arr, ci) => {
      ctx.fillStyle = T.leaf[ci]; ctx.beginPath();
      for (const lf of arr) { const v = lf.st.vis * lf.st.L; if (lf.s > v) continue; leafPath(ctx, tree, lf, Math.min(1, Math.max(0.3, (v - lf.s) / 22))); }
      ctx.fill();
    });

    /* 数据枝：完成的段落长满叶子，进行中的位置冒新芽，未做的段只是细枝 */
    tree.dataStrands.forEach((st, bi) => {
      const v = dv[bi]; if (!v || v.len <= 0) return;
      const isF = focus === bi, dim = focus != null && !isF;
      ctx.globalAlpha = dim ? 0.38 : 1;
      ctx.strokeStyle = v.dry ? T.dry : T.stemStrong;
      ctx.lineWidth = lw(v.dry ? 1.3 : isF ? 2.6 : 1.8);
      ctx.beginPath(); stemPath(ctx, tree, st, v.len); ctx.stroke();
      if (v.dry) {
        ctx.fillStyle = T.dryLeaf; ctx.beginPath();
        st.leaves.forEach((lf, i) => { if (i % 3 === 0 && lf.s < v.len) leafPath(ctx, tree, lf, 0.75); });
        ctx.fill();
      } else {
        for (let ci = 0; ci < 4; ci++) {
          ctx.fillStyle = T.leaf[ci]; ctx.beginPath();
          for (const lf of st.leaves) {
            if (lf.c !== ci) continue;
            if (lf.s <= v.leafy) leafPath(ctx, tree, lf, 1);
            else if (ci === 3 && lf.s <= v.bud) leafPath(ctx, tree, lf, 0.6);
          }
          ctx.fill();
        }
        if (v.bud > v.leafy) {
          ctx.fillStyle = T.leaf[3]; ctx.beginPath();
          for (const lf of st.leaves) if (lf.c !== 3 && lf.s > v.leafy && lf.s <= v.bud && lf.s > v.bud - 26) leafPath(ctx, tree, lf, 0.55);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    });
    ctx.restore();
  }

  /* 地面：在树之后画，盖住树根，像种在土里 */
  const gy = tree.groundY;
  const gg = ctx.createLinearGradient(0, gy, 0, tree.H);
  gg.addColorStop(0, T.ground); gg.addColorStop(1, T.ground2);
  ctx.fillStyle = gg; ctx.beginPath(); ctx.moveTo(0, tree.H);
  for (let x = 0; x <= tree.W + 24; x += 24) ctx.lineTo(x, gy + 1.6 * Math.sin(x * 0.013) + 1.2 * Math.sin(x * 0.041 + 1));
  ctx.lineTo(tree.W, tree.H); ctx.closePath(); ctx.fill();
  if (S > 0.001) {
    ctx.fillStyle = T.ground2; ctx.globalAlpha = 0.6; ctx.beginPath();
    ctx.ellipse(bx + 4, gy + 5, Math.max(10, tree.R * 0.42 * S), 5 + 3 * S, 0, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
  }
  ctx.strokeStyle = T.grass; ctx.lineWidth = 1; ctx.lineCap = 'round'; ctx.beginPath();
  for (const g of RD.grass) {
    const y0 = gy + 3 + 1.6 * Math.sin(g.x * 0.013) + 1.2 * Math.sin(g.x * 0.041 + 1);
    const sw = o.windOn ? Math.sin(t * 1.4 + g.ph + g.x * 0.03) * 1.1 : 0;
    ctx.moveTo(g.x, y0); ctx.quadraticCurveTo(g.x + g.lean * 0.4, y0 - g.h * 0.6, g.x + g.lean + sw, y0 - g.h);
  }
  ctx.stroke();

  /* 发芽期的两片子叶 */
  if (S > 0.001 && S < 0.42) {
    const a = 1 - Math.max(0, (S - 0.26) / 0.16);
    const top = { x: bx + (tree.trunk.pts[tree.trunk.pts.length - 1].x - bx) * S, y: by + (tree.forkY - by) * S };
    ctx.globalAlpha = a; ctx.fillStyle = T.leaf[1];
    for (const sd of [-1, 1]) {
      ctx.beginPath(); ctx.moveTo(top.x, top.y);
      ctx.quadraticCurveTo(top.x + sd * 6, top.y - 11, top.x + sd * 13, top.y - 6);
      ctx.quadraticCurveTo(top.x + sd * 8, top.y + 1, top.x, top.y); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
}

/* 远山：两层柔和的山脊线 */
function drawHills(svg, W, H, groundY) {
  const ridge = (y0, amp, f1, f2, ph) => {
    let d = `M0 ${H} L0 ${y0}`;
    for (let x = 0; x <= W + 20; x += 20) d += ` L${x} ${(y0 - amp * (0.6 * Math.sin(x * f1 + ph) + 0.4 * Math.sin(x * f2 + ph * 2))).toFixed(1)}`;
    return d + ` L${W} ${H} Z`;
  };
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.innerHTML = `<path d="${ridge(groundY - H * 0.2, H * 0.05, 0.006, 0.017, 0.8)}" fill="var(--hill-far)"/><path d="${ridge(groundY - H * 0.08, H * 0.035, 0.009, 0.023, 2.1)}" fill="var(--hill-near)"/>`;
}



const STATUS_TXT = { done: '完成', doing: '进行中', todo: '待做', blocked: '卡住' };
const ICON = {
  done: '<svg viewBox="0 0 15 15" aria-hidden="true"><path d="M4.1 7.9l2.2 2.2 4.6-5" fill="none" stroke="var(--on-node)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  doing: '<svg viewBox="0 0 15 15" aria-hidden="true"><circle cx="7.5" cy="7.5" r="2.4" fill="var(--on-node)"/></svg>',
  todo: '',
  blocked: '<svg viewBox="0 0 15 15" aria-hidden="true"><path d="M4.4 7.5h6.2" stroke="var(--stuck)" stroke-width="2.1" stroke-linecap="round"/></svg>'
};
const FRUIT_SVG = ground => `<svg viewBox="0 0 36 40" aria-hidden="true">
  <path d="M18 4c0 3-.4 5-1 7" stroke="var(--bark)" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <path d="M17.6 8c2.9-2.8 6.9-2.6 8.9-.8-2.9 2.4-6.1 2.6-8.9.8z" fill="var(--leaf-3)"/>
  <circle class="ring" cx="17" cy="21" r="11" fill="none" stroke="transparent" stroke-width="2"/>
  <circle class="body" cx="17" cy="21" r="8.6"/>
  <ellipse cx="13.8" cy="17.4" rx="2.8" ry="1.9" fill="#fff" opacity=".42"/>
  ${ground ? '<circle cx="26.5" cy="27.5" r="5.4" fill="var(--done)" stroke="var(--paper)" stroke-width="1.5"/><path d="M24.2 27.6l1.6 1.6 3-3.3" fill="none" stroke="var(--on-node)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' : ''}
</svg>`;
const SEED_SVG = `<svg viewBox="0 0 40 34" aria-hidden="true">
  <ellipse cx="20" cy="27" rx="13" ry="3.2" fill="var(--ground-2)" opacity=".9"/>
  <path d="M20 5.5c7 3 9 13 2.2 21-2.6 2.6-6.2 1.6-7.2-1.8-2.4-8-1-15.6 5-19.2z" fill="var(--seed)"/>
  <path d="M19.6 8.6c1.6 5 1.2 11-.9 16.6" stroke="var(--bark-lo)" stroke-width="1.1" fill="none" opacity=".55" stroke-linecap="round"/>
  <ellipse cx="18" cy="12.5" rx="1.7" ry="3.1" fill="#fff" opacity=".28"/>
</svg>`;



const clip = (s, max) => { let w = 0, out = ''; for (const ch of String(s||'')) { const cw = ch.charCodeAt(0) < 0x2E80 ? 0.56 : 1; if (w + cw > max + 0.01) return out.trimEnd() + '…'; w += cw; out += ch; } return out; };

global.Willow = {
  mulberry32, cubic, sampleCubic, arcLen, tangentAt, hang, makeLeaves,
  buildTree, strandPoint, strandRestPoint,
  RD, readTokens, prepRender, sway, taperPath, leafPath, stemPath,
  drawScene, drawHills,
  STATUS_TXT, ICON, FRUIT_SVG, SEED_SVG, clip
};
})(typeof window !== 'undefined' ? window : globalThis);
