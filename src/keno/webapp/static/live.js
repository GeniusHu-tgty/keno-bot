"use strict";
const $ = (id) => document.getElementById(id);
let liveJobId = null;
let lastPreview = null;
let modalRunId = null;
let paytables = {};
let selected = [];
let lastDrawn = [];
let connected = false;

async function api(path, method = "GET", body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try { res = await fetch(path, opts); }
  catch (err) { return { ok: false, error: "连不上本地服务" }; }
  const text = await res.text();
  try { return JSON.parse(text); }
  catch (err) { return { ok: false, error: `HTTP ${res.status}` }; }
}

function toast(msg, ms) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), ms || 4200);
}
function clsP(v) { const n = Number(v); return n > 0 ? "pos" : (n < 0 ? "neg" : ""); }
function money(v, sign) {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  const s = "$" + Math.abs(n).toFixed(8);
  if (n < 0) return "-" + s;
  if (sign && n > 0) return "+" + s;
  return s;
}
function fmtDur(sec) {
  const n = Number(sec);
  if (!isFinite(n) || n <= 0) return "未开始";
  const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60), s = Math.floor(n % 60);
  return `${h}小时 ${m}分 ${s}秒`;
}
function colorList(nums, hits) {
  const hitSet = new Set((hits || []).map(Number));
  return `[${(nums || []).map((n) => `<span class="${hitSet.has(Number(n)) ? "n-hit" : "n-miss"}">${n}</span>`).join(",")}]`;
}

function numOr(id, fallback) {
  const el = $(id);
  if (!el) return fallback;
  const raw = el.value;
  if (raw === "" || raw == null) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}
function payload() {
  const amounts = $("custom-amounts").value.trim();
  const first = (amounts.split(",")[0] || "0.0001").trim();
  if ($("base-bet").value.trim() === "") $("base-bet").value = first;
  return {
    money: "combo",
    picks: "combo",
    base_bet: $("base-bet").value.trim() || first,
    custom_amounts: amounts,
    start_level: Number($("start-level").value) || 1,
    max_level: Number($("max-level").value) || 1,
    reset_on_max_loss: $("reset-max").checked,
    recon_on: $("recon-on").value === "1",
    recon_n_loss: numOr("recon-n-loss", 0),
    recon_n_win: numOr("recon-n-win", 1),
    recon_real_n: numOr("recon-real-n", 1),
    recon_min: $("recon-min").value.trim() || "0.0001",
    recon_max: $("recon-max").value.trim() || "0.0001",
    recon_numbers: $("recon-numbers").value,
    recon_return_on_real_win: $("recon-return-win") ? $("recon-return-win").checked : true,
    recon_abort_on_real_loss: $("recon-abort-loss") ? $("recon-abort-loss").checked : false,
    recon_abort_after: numOr("recon-abort-after", 0),
    rest_seconds: numOr("rest-seconds", 180),
    hard_rest_seconds: numOr("hard-rest-seconds", 900),
    autohost: $("autohost") ? $("autohost").checked : false,
    stop_on_max_win: $("stop-max-win") ? $("stop-max-win").checked : true,
    playbook: $("playbook") ? $("playbook").checked : false,
    after_bank: $("after-bank") ? $("after-bank").value : "stop",
    session_stop_win: $("win") ? $("win").value : "",
    session_stop_loss: $("loss") ? $("loss").value : "",
    daily_stop_win: $("daily-win") ? $("daily-win").value : "",
    daily_stop_loss: $("daily-loss") ? $("daily-loss").value : "",
    stop_on_mult: $("fat-mult") ? $("fat-mult").value : "8",
    keep_on_win: $("keep-on-win").value === "1",
    pick_count: Number($("pick-count").value) || 10,
    risk: $("risk").value,
    force_min: false,
    max_bet: "1000",
    manual_picks: selected.slice(),
    run_name: ($("run-name") && $("run-name").value.trim()) || "",
  };
}

function renderBoard() {
  const el = $("board");
  el.innerHTML = "";
  const pickSet = new Set(selected.map(Number));
  const drawSet = new Set(lastDrawn.map(Number));
  for (let n = 1; n <= 40; n++) {
    const cell = document.createElement("div");
    cell.className = "cell";
    cell.textContent = n;
    if (drawSet.size && drawSet.has(n) && pickSet.has(n)) cell.classList.add("hit");
    else if (pickSet.has(n)) cell.classList.add(["sel", "sel2", "sel3"][(n * 7) % 3]);
    else if (drawSet.has(n)) cell.classList.add("draw");
    cell.onclick = () => {
      const i = selected.indexOf(n);
      if (i >= 0) selected.splice(i, 1);
      else if (selected.length < (Number($("pick-count").value) || 10)) selected.push(n);
      selected.sort((a, b) => a - b);
      renderBoard();
    };
    el.appendChild(cell);
  }
}

function renderPaytable(risk) {
  const table = paytables[risk] || paytables.low || [];
  $("paytable").innerHTML = table.map((m, hits) =>
    `<div class="pt-row"><span>${hits} 命中</span><b>x${m}</b></div>`
  ).join("");
}

function renderHeat(heat, recs, zones) {
  const el = $("heatmap");
  el.innerHTML = "";
  for (let n = 1; n <= 40; n++) {
    const cell = (heat && heat[n]) || (heat && heat[String(n)]) || { freq: 0 };
    const freq = Number(cell.freq || 0);
    const div = document.createElement("div");
    div.className = "heat" + (freq >= 32 ? " hot" : "");
    const t = Math.max(0, Math.min(1, freq / 50));
    div.style.background = `rgba(${40 + t * 80}, ${40 + t * 140}, ${80 + t * 40}, .9)`;
    div.innerHTML = `<div class="n">${n}</div><div class="f">${freq.toFixed(1)}</div>`;
    el.appendChild(div);
  }
  $("recs").innerHTML = (recs || []).map((r) =>
    `<span class="rec">${r.n} ${Number(r.freq || 0).toFixed(1)} ${(r.tags || []).join("+")}</span>`
  ).join("");
  $("zones").innerHTML = (zones || []).map((z) =>
    `<span class="zone">${z.label} 均分 ${z.avg} | 热 ${z.hot}</span>`
  ).join("");
}

function renderLevel(rows, dash, tableId) {
  const el = $(tableId || "tbl-level");
  if (!el) return;
  const head = `<tr><th>等级</th><th>局数</th><th>成功</th><th>失败</th><th>成功率</th><th>投注合计</th><th>回收合计</th><th>盈亏</th></tr>`;
  let body = (rows || []).map((r) =>
    `<tr><td>${r.label || (r.level === 0 ? "侦察" : r.level + "档")}</td><td>${r.n}</td><td>${r.wins}</td><td>${r.fails}</td>` +
    `<td>${((r.winrate || 0) * 100).toFixed(0)}%</td><td>${money(r.staked)}</td><td>${money(r.returned)}</td>` +
    `<td class="${clsP(r.profit)}">${money(r.profit, true)}</td></tr>`
  ).join("");
  if (dash && (dash.rounds || 0) > 0) {
    body += `<tr><td>合计</td><td>${dash.rounds}</td><td>${dash.wins}</td><td>${dash.fails}</td>` +
      `<td>${((dash.winrate || 0) * 100).toFixed(1)}%</td><td>${money(dash.staked)}</td><td>${money(dash.returned)}</td>` +
      `<td class="${clsP(dash.profit)}">${money(dash.profit, true)}</td></tr>`;
  }
  el.innerHTML = head + body;
}
function renderStreak(rows, cur, maxv, tableId, capId) {
  const cap = $(capId || "streak-cap");
  if (cap) cap.textContent = `最大 ${maxv || 0}连败 | 当前 ${cur || 0}连败`;
  const el = $(tableId || "tbl-streak");
  if (!el) return;
  const maxn = Math.max(1, ...(rows || []).map((r) => r.n));
  const head = `<tr><th>连败</th><th>次数</th><th></th></tr>`;
  el.innerHTML = head + (rows || []).map((r) => {
    const w = Math.round(100 * r.n / maxn);
    const cls = r.k >= 5 ? "bar orange" : "bar";
    return `<tr><td>${r.k}连败</td><td>${r.n}次</td><td><span class="${cls}" style="width:${w}%"></span></td></tr>`;
  }).join("");
}
function renderHits(rows, tableId) {
  const el = $(tableId || "tbl-hits");
  if (!el) return;
  const head = `<tr><th>命中</th><th>次数</th><th>占比</th><th>投注合计</th><th>回收合计</th><th>盈亏</th></tr>`;
  el.innerHTML = head + (rows || []).map((r) =>
    `<tr><td>${r.hits} 命中</td><td>${r.n}</td><td>${((r.pct || 0) * 100).toFixed(1)}%</td>` +
    `<td>${money(r.staked)}</td><td>${money(r.returned)}</td>` +
    `<td class="${clsP(r.profit)}">${money(r.profit, true)}</td></tr>`
  ).join("");
}
function attachCum(rows, newestFirst) {
  const list = rows || [];
  const chrono = newestFirst ? list.slice().reverse() : list.slice();
  let cum = 0;
  const mapped = chrono.map((r) => {
    const raw = (r.profit != null && String(r.profit) !== "") ? r.profit : (Number(r.payout) - Number(r.bet));
    const pnl = Number(raw) || 0;
    if (r.cum_profit != null && String(r.cum_profit) !== "") cum = Number(r.cum_profit);
    else cum += pnl;
    return { r, cum };
  });
  if (newestFirst) mapped.reverse();
  return mapped;
}
function renderHist(el, rows, newestFirst) {
  if (!el) return;
  const tagged = Array.isArray(rows) && rows.length && rows[0] && rows[0].r ? rows : attachCum(rows || [], !!newestFirst);
  const head = `<tr><th>#</th><th>档</th><th>投注</th><th>命中</th><th>倍率</th><th>盈亏</th><th>累计</th><th>号码</th><th>开奖</th></tr>`;
  el.innerHTML = head + tagged.map((item, i) => {
    const r = item.r;
    const win = Number(r.payout) >= Number(r.bet);
    const lv = r.level;
    const lvText = r.recon || r.stage === "侦察" || lv === 0 ? "侦察" : ((lv == null || lv === "") ? "—" : `${lv}档`);
    return `<tr><td>${r.n || (i + 1)}</td><td>${lvText}</td>` +
      `<td class="${win ? "pos" : "neg"}">${money(r.bet)}</td>` +
      `<td>${r.hits ?? ""}</td><td>x${Number(r.multiplier || 0)}</td>` +
      `<td class="${clsP(r.profit)}">${money(r.profit, true)}</td>` +
      `<td class="${clsP(item.cum)}">${money(item.cum, true)}</td>` +
      `<td class="mono">${colorList(r.picks, r.drawn)}</td>` +
      `<td class="mono">${colorList(r.drawn, r.picks)}</td></tr>`;
  }).join("");
}
function paintHist() {
  const el = $("tbl-hist");
  if (!el) return;
  const tagged = attachCum(histAllRows, true);
  if (!tagged.length) {
    renderHist(el, []);
    renderPager($("hist-pager"), 1, 1, 0, () => {});
    return;
  }
  const size = pageSizeOf("hist-page-size", 30);
  const pages = Math.max(1, Math.ceil(tagged.length / size));
  if (histPage > pages) histPage = pages;
  if (histPage < 1) histPage = 1;
  const start = (histPage - 1) * size;
  renderHist(el, tagged.slice(start, start + size), true);
  renderPager($("hist-pager"), histPage, pages, tagged.length, (p) => {
    histPage = p;
    paintHist();
  });
}
function renderEquity(el, curve, dash) {
  if (!el) return;
  const pts = curve || [];
  if (!pts.length) {
    el.innerHTML = `<p class="hint">这次还没有局</p>`;
    return;
  }
  const w = 720, h = 190, padL = 54, padR = 16, padT = 18, padB = 28;
  const ys = pts.map((p) => Number(p.cum));
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(0, ...ys);
  const spanY = maxY - minY || 1;
  const n = pts.length;
  const xAt = (i) => padL + (i / Math.max(n - 1, 1)) * (w - padL - padR);
  const yAt = (v) => padT + (1 - (v - minY) / spanY) * (h - padT - padB);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(Number(p.cum)).toFixed(1)}`).join(" ");
  const zero = yAt(0);
  const last = ys[ys.length - 1];
  const color = last >= 0 ? "#34d399" : "#f87171";
  const area = `M${xAt(0).toFixed(1)},${zero.toFixed(1)} ${pts.map((p, i) => `L${xAt(i).toFixed(1)},${yAt(Number(p.cum)).toFixed(1)}`).join(" ")} L${xAt(n - 1).toFixed(1)},${zero.toFixed(1)} Z`;
  const peakN = Number((dash && dash.peak_n) || 0);
  const troughN = Number((dash && dash.trough_n) || 0);
  const marks = [];
  function mark(idx, label, fill) {
    if (idx < 1 || idx > n) return;
    const i = idx - 1;
    const v = ys[i];
    marks.push(
      `<circle class="eq-dot" cx="${xAt(i).toFixed(1)}" cy="${yAt(v).toFixed(1)}" r="4" fill="${fill}"/>` +
      `<text class="eq-lab" x="${Math.min(xAt(i) + 6, w - 80).toFixed(1)}" y="${Math.max(12, yAt(v) - 8).toFixed(1)}">${label} #${idx} ${money(v, true)}</text>`
    );
  }
  mark(peakN, "高峰", "#34d399");
  if (troughN && troughN !== peakN) mark(troughN, "最低", "#f87171");
  el.innerHTML =
    `<div class="equity-meta">高峰 ${money(dash && dash.peak, true)}　最低 ${money(dash && dash.trough, true)}　收口 ${money(last, true)}　共 ${n} 局</div>` +
    `<svg viewBox="0 0 ${w} ${h}" class="equity-svg" preserveAspectRatio="none">` +
    `<line x1="${padL}" x2="${w - padR}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" class="eq-zero"/>` +
    `<path class="eq-fill" d="${area}" fill="${color}"/>` +
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="2"/>` +
    marks.join("") +
    `</svg>`;
}
function renderModalHero(run, dash) {
  const el = $("modal-hero");
  if (!el) return;
  const d = dash || {};
  const cells = [
    [money(d.profit, true), "总盈利", clsP(d.profit)],
    [d.rounds || 0, "局数", ""],
    [((d.winrate || 0) * 100).toFixed(1) + "%", "成功率", ""],
    [fmtDur(run.duration_sec), "已打时长", ""],
    [money(d.staked), "投资金", ""],
    [money(d.returned), "回收金", ""],
    [money(d.peak, true), "累计高峰", "pos"],
    [money(d.trough, true), "累计最低", "neg"],
  ];
  el.innerHTML = cells.map((c) =>
    `<div class="mh"><div class="v ${c[2]}">${c[0]}</div><div class="k">${c[1]}</div></div>`
  ).join("");
}

function settingsSnap() {
  return {
    risk: $("risk").value,
    pick_count: Number($("pick-count").value) || 10,
    custom_amounts: $("custom-amounts").value.trim() || "0.0001",
    keep_on_win: $("keep-on-win").value === "1",
    recon_on: $("recon-on").value === "1",
    max_level: Number($("max-level").value) || 1,
    start_level: Number($("start-level").value) || 1,
  };
}

let allRuns = [];
let filteredRuns = [];
let runPage = 1;
let histAllRows = [];
let histPage = 1;

function pageSizeOf(id, fallback) {
  const el = $(id);
  const n = Number(el && el.value);
  return [10, 20, 30, 50].includes(n) ? n : fallback;
}
function rememberPageSize(id, value) {
  try { localStorage.setItem("keno-" + id, String(value)); } catch (err) { /* ignore */ }
}
function restorePageSize(id, fallback) {
  const el = $(id);
  if (!el) return;
  try {
    const saved = localStorage.getItem("keno-" + id);
    if (saved && [...el.options].some((o) => o.value === saved)) el.value = saved;
    else el.value = String(fallback);
  } catch (err) {
    el.value = String(fallback);
  }
}
function renderPager(el, page, pages, total, onGo) {
  if (!el) return;
  if (!total) {
    el.innerHTML = "";
    return;
  }
  const prev = Math.max(1, page - 1);
  const next = Math.min(pages, page + 1);
  el.innerHTML =
    `<span class="pager-info">第 ${page}/${pages} 页 · 共 ${total} 条</span>` +
    `<button type="button" class="btn ghost" data-p="1"${page <= 1 ? " disabled" : ""}>首页</button>` +
    `<button type="button" class="btn ghost" data-p="${prev}"${page <= 1 ? " disabled" : ""}>上一页</button>` +
    `<button type="button" class="btn ghost" data-p="${next}"${page >= pages ? " disabled" : ""}>下一页</button>` +
    `<button type="button" class="btn ghost" data-p="${pages}"${page >= pages ? " disabled" : ""}>末页</button>`;
  el.querySelectorAll("button[data-p]").forEach((btn) => {
    btn.onclick = () => {
      const p = Number(btn.getAttribute("data-p"));
      if (!p || p === page) return;
      onGo(p);
    };
  });
}
function todayYmd() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}
function fillStrategySelect(runs) {
  const sel = $("run-strategy");
  if (!sel) return;
  const cur = sel.value;
  const seen = new Set();
  const opts = [];
  (runs || []).forEach((r) => {
    const k = r.strategy_key || "";
    if (!k || seen.has(k)) return;
    seen.add(k);
    opts.push([k, r.strategy_label || k]);
  });
  sel.innerHTML = `<option value="">全部策略</option>` + opts.map(([k, lab]) =>
    `<option value="${String(k).replace(/"/g, "&quot;")}">${String(lab).replace(/</g, "")}</option>`
  ).join("");
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
}
function applyRunFilters(keepPage) {
  const from = ($("run-from") && $("run-from").value) || "";
  const to = ($("run-to") && $("run-to").value) || "";
  const q = (($("run-q") && $("run-q").value) || "").trim().toLowerCase();
  const st = ($("run-strategy") && $("run-strategy").value) || "";
  filteredRuns = allRuns.filter((r) => {
    const day = r.day || "";
    if (from && day && day < from) return false;
    if (to && day && day > to) return false;
    if (st && r.strategy_key !== st) return false;
    if (q) {
      const blob = `${r.name || ""} ${r.when || ""} ${r.brief || ""} ${r.strategy_label || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
  if (!keepPage) runPage = 1;
  renderRuns();
}
function bindRunFilters() {
  restorePageSize("run-page-size", 20);
  restorePageSize("hist-page-size", 30);
  ["run-from", "run-to", "run-q", "run-strategy"].forEach((id) => {
    const el = $(id);
    if (!el || el._bound) return;
    el._bound = true;
    el.onchange = () => applyRunFilters();
    el.oninput = () => applyRunFilters();
  });
  if ($("run-page-size") && !$("run-page-size")._bound) {
    $("run-page-size")._bound = true;
    $("run-page-size").onchange = () => {
      rememberPageSize("run-page-size", $("run-page-size").value);
      runPage = 1;
      renderRuns();
    };
  }
  if ($("hist-page-size") && !$("hist-page-size")._bound) {
    $("hist-page-size")._bound = true;
    $("hist-page-size").onchange = () => {
      rememberPageSize("hist-page-size", $("hist-page-size").value);
      histPage = 1;
      paintHist();
    };
  }
  if ($("run-today") && !$("run-today")._bound) {
    $("run-today")._bound = true;
    $("run-today").onclick = () => {
      const t = todayYmd();
      $("run-from").value = t;
      $("run-to").value = t;
      applyRunFilters();
    };
  }
  if ($("run-all-days") && !$("run-all-days")._bound) {
    $("run-all-days")._bound = true;
    $("run-all-days").onclick = () => {
      $("run-from").value = "";
      $("run-to").value = "";
      applyRunFilters();
    };
  }
}
function renderRuns() {
  const el = $("run-list");
  if (!el) return;
  const runs = filteredRuns;
  if (!runs || !runs.length) {
    el.innerHTML = `<p class="hint">这一筛没有记录。改日期或点「全部日期」。</p>`;
    renderPager($("run-pager"), 1, 1, 0, () => {});
    renderPager($("run-pager-bottom"), 1, 1, 0, () => {});
    return;
  }
  const size = pageSizeOf("run-page-size", 20);
  const pages = Math.max(1, Math.ceil(runs.length / size));
  if (runPage > pages) runPage = pages;
  if (runPage < 1) runPage = 1;
  const start = (runPage - 1) * size;
  const pageRows = runs.slice(start, start + size);
  const go = (p) => { runPage = p; renderRuns(); };
  renderPager($("run-pager"), runPage, pages, runs.length, go);
  renderPager($("run-pager-bottom"), runPage, pages, runs.length, go);
  el.innerHTML = pageRows.map((r) => {
    const profitCls = clsP(r.profit);
    const nick = String(r.name || "").trim();
    return `<div class="run-card ${r.open ? "open" : ""}" data-id="${r.id}">
      <div><input class="name" data-id="${r.id}" placeholder="${String(r.when || "").replace(/"/g, "&quot;")}" value="${nick.replace(/"/g, "&quot;")}" />
        <span class="when">${r.when}${r.open ? " · 进行中" : ""}</span></div>
      <div class="brief">${r.brief || ""}</div>
      <div class="meta"><span class="${profitCls}">${money(r.profit, true)}</span> · ${r.rounds || 0} 局 · 成功率 ${((r.winrate || 0) * 100).toFixed(1)}%</div>
      <div class="run-actions">
        <button type="button" class="btn ghost btn-open" data-id="${r.id}">打开</button>
        <button type="button" class="btn ghost btn-export" data-id="${r.id}">导出</button>
        <button type="button" class="btn red btn-del" data-id="${r.id}">删除</button>
      </div>
    </div>`;
  }).join("");
  el.querySelectorAll(".run-card").forEach((card) => {
    card.onclick = (ev) => {
      if (ev.target.closest("input,button")) return;
      openRun(card.getAttribute("data-id"));
    };
  });
  el.querySelectorAll("input.name").forEach((inp) => {
    inp.onclick = (ev) => ev.stopPropagation();
    inp.onchange = async () => {
      await api("/api/live/runs/rename", "POST", { id: inp.getAttribute("data-id"), name: inp.value.trim() });
      toast("已改名");
    };
  });
  el.querySelectorAll(".btn-open").forEach((btn) => {
    btn.onclick = (ev) => { ev.stopPropagation(); openRun(btn.getAttribute("data-id")); };
  });
  el.querySelectorAll(".btn-export").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      window.location.href = "/api/live/runs?id=" + encodeURIComponent(btn.getAttribute("data-id")) + "&export=1";
    };
  });
  el.querySelectorAll(".btn-del").forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const id = btn.getAttribute("data-id");
      if (!window.confirm("确定删除这次记录？空的、打错的可以删。删了列表里就没了。")) return;
      if (!window.confirm("再确认一次：删除后不能从列表恢复。")) return;
      const res = await api("/api/live/runs/delete", "POST", { id });
      if (!res.ok) { toast(res.error || "删除失败"); return; }
      toast("已删除");
      await loadAll();
    };
  });
}

function renderStage(plan, st) {
  const amounts = (plan && plan.ladder && plan.ladder.length)
    ? plan.ladder
    : ($("custom-amounts").value.trim() || "0.0001").split(",").map((s) => s.trim()).filter(Boolean);
  const maxLv = Math.max(1, Number((plan && plan.max_level) || $("max-level").value) || amounts.length);
  const cur = Number((plan && plan.level) || (st && st.desk && st.desk.level) || 1);
  const nextAmt = (plan && plan.amount) || amounts[Math.min(cur, amounts.length) - 1] || amounts[0];
  const risk = $("risk").value;
  const winHits = risk === "low" ? 2 : 3;
  const reconOn = $("recon-on") && $("recon-on").value === "1";
  const inRecon = !!(plan && plan.recon);
  $("stage-rule").textContent =
    (reconOn
      ? "侦察 0.0001 赢了才上实战梯子；实战输了进下一档，赢了或顶档输了回侦察。"
      : "输了（收回 < 投下）进下一档；赢了（收回 ≥ 投下）回到 1 档。") +
    (risk === "low" ? " 低等：0/1 命中算输，2 命中起算赢。" : " 中等/典型：0/1/2 命中算输，3 命中起算赢。") +
    ` 号：赢了留，输了换。最多 ${maxLv} 档。`;
  const playing = st && st.running;
  const nowLabel = inRecon
    ? `当前侦察 · 下一注 $${Number(nextAmt).toFixed(8)}`
    : `当前第 ${cur} 档 · 下一注 $${Number(nextAmt).toFixed(8)}`;
  $("stage-now").textContent = playing
    ? `${nowLabel} · 计时已开始`
    : `${nowLabel} · 还没点开始，不计时`;
  $("stage-ladder").innerHTML = amounts.slice(0, maxLv).map((amt, i) => {
    const lv = i + 1;
    const on = !inRecon && lv === cur;
    return `<div class="stage-chip ${on ? "on" : ""}"><div class="lv">${lv} 档${on ? " · 现在" : ""}</div><div class="amt">$${Number(amt).toFixed(8)}</div></div>`;
  }).join("");
}

function curveFromRows(rows) {
  return attachCum(rows, false).map((item, i) => ({
    n: Number(item.r.n) || (i + 1),
    profit: item.r.profit,
    cum: item.cum,
  }));
}
function withEquity(dash, rows) {
  const d = Object.assign({}, dash || {});
  const curve = (d.curve && d.curve.length) ? d.curve : curveFromRows(rows || []);
  d.curve = curve;
  if (curve.length) {
    const ys = curve.map((p) => Number(p.cum));
    let peak = 0, trough = 0, peakN = 0, troughN = 0;
    ys.forEach((v, i) => {
      if (v > peak) { peak = v; peakN = i + 1; }
      if (v < trough) { trough = v; troughN = i + 1; }
    });
    if (d.peak == null || d.peak === "") d.peak = peak;
    if (d.trough == null || d.trough === "") d.trough = trough;
    if (!d.peak_n) d.peak_n = peakN;
    if (!d.trough_n) d.trough_n = troughN;
  }
  return d;
}
async function openRun(id) {
  const res = await api("/api/live/runs?id=" + encodeURIComponent(id));
  if (!res.ok || !res.run) { toast(res.error || "打不开这次记录"); return; }
  const run = res.run;
  const rows = run.records || [];
  const dash = withEquity(run.dashboard, rows);
  modalRunId = id;
  $("modal-title").textContent = run.name || run.when;
  $("modal-brief").textContent = `${run.when} · ${run.brief}` +
    (run.open ? " · 进行中" : "") +
    ` · 赢的加起来 ${money(dash.win_profit, true)}　输的加起来 ${money(dash.lose_profit, true)}`;
  renderModalHero(run, dash);
  renderEquity($("modal-equity"), dash.curve, dash);
  renderLevel(dash.levels, dash, "modal-tbl-level");
  const useReal = (dash.recon_rounds || 0) > 0 && dash.real_streaks;
  renderStreak(
    useReal ? dash.real_streaks : dash.streaks,
    useReal ? dash.real_current_streak : dash.current_streak,
    useReal ? dash.real_max_streak : dash.max_streak,
    "modal-tbl-streak",
    "modal-streak-cap"
  );
  if (useReal) {
    const cap = $("modal-streak-cap");
    if (cap) cap.textContent = `实战 最大 ${dash.real_max_streak || 0}连败 | 当前 ${dash.real_current_streak || 0}连败（侦察不计入）`;
  }
  renderHits(dash.hits, "modal-tbl-hits");
  renderHist($("modal-hist"), rows, false);
  $("run-modal").classList.remove("hidden");
}

function renderHero(st) {
  const d = (st.desk && st.desk.dashboard) || st.session_stats || {};
  $("h-profit").textContent = money(d.profit, true);
  $("h-profit").className = "v " + clsP(d.profit);
  $("h-rounds").textContent = d.rounds || 0;
  $("h-winrate").textContent = ((d.winrate || d.success_rate || 0) * 100).toFixed(1) + "%";
  $("h-staked").textContent = money(d.staked);
  $("h-returned").textContent = money(d.returned);
  $("h-balance").textContent = st.balance != null ? money(st.balance) : "—";
  $("h-level").textContent = (st.desk && st.desk.recon) ? "侦察" : ((st.desk && st.desk.level_label) || (st.desk && st.desk.level) || 1);
  $("h-time").textContent = fmtDur((st.session_stats || {}).duration_sec);
  const split = $("h-split");
  if (split) {
    split.innerHTML = d.rounds
      ? `赢的加起来 ${money(d.win_profit, true)}　输的加起来 ${money(d.lose_profit, true)}　净 ${money(d.profit, true)}`
      : "还没有这一次的局";
    split.className = "hero-split " + clsP(d.profit);
  }
}

function renderLast(row) {
  if (!row) return;
  lastDrawn = row.drawn || [];
  selected = (row.picks || selected).map(Number);
  const win = Number(row.payout) >= Number(row.bet);
  $("last-line").textContent =
    `#${row.n || ""} ${win ? "WIN" : "LOSS"} ${row.hits}命中 x${row.multiplier} ${money(row.payout)} （总 ${money(row.profit, true)}）`;
  $("last-line").style.color = win ? "#86efac" : "#f87171";
  renderBoard();
}

function renderPreview(plan) {
  if (!plan) return;
  lastPreview = plan;
  if (plan.picks && plan.picks.length && selected.length !== plan.picks.length) {
    selected = plan.picks.map(Number);
    renderBoard();
  } else if (plan.picks && !selected.length) {
    selected = plan.picks.map(Number);
    renderBoard();
  }
  if (plan.heatmap) renderHeat(plan.heatmap, plan.recommended, plan.zones);
  $("h-level").textContent = plan.recon ? "侦察" : (plan.level || $("h-level").textContent);
}

async function refreshPreview() {
  const plan = await api("/api/live/preview", "POST", payload());
  if (plan && plan.ok !== false) {
    renderPreview(plan);
    renderStage(plan, { running: !!liveJobId });
  }
}

function renderStatus(st) {
  connected = st.status === "connected";
  const acct = $("acct");
  if (acct) acct.title = st.error || "";
  if (connected) acct.textContent = st.user_name || "已连接";
  else if (st.status === "need_login") {
    const waited = Number(st.wait_seconds || 0);
    acct.textContent = waited > 0
      ? `等待登录 ${waited}s…`
      : "请在 Chrome 窗口登录 Stake";
    setConnectBanner(st);
  } else if (st.status === "error") {
    acct.textContent = "连接没成功，点「连接」重试";
    setConnectBanner(st);
  } else if (st.connecting || st.status === "opening") acct.textContent = "正在打开 Stake…";
  else acct.textContent = "未连接";
  $("btn-start").disabled = !connected || !!st.running;
  if ($("btn-loop")) $("btn-loop").disabled = !connected || !!st.running;
  if ($("btn-host-start")) $("btn-host-start").disabled = !connected || !!st.running;
  $("btn-one").disabled = !connected || !!st.running;
  $("btn-stop").disabled = !st.running;
  if ($("btn-host-stop")) $("btn-host-stop").disabled = !st.running;
  if (st.paytables) paytables = st.paytables;
  renderPaytable($("risk").value);
  renderHero(st);
  const desk = st.desk || {};
  if (desk.dashboard) {
    const d = desk.dashboard;
    renderLevel(d.levels, d);
    const useReal = (d.recon_rounds || 0) > 0 && d.real_streaks;
    renderStreak(
      useReal ? d.real_streaks : d.streaks,
      useReal ? d.real_current_streak : d.current_streak,
      useReal ? d.real_max_streak : d.max_streak
    );
    if (useReal) {
      const cap = $("streak-cap");
      if (cap) cap.textContent = `实战 最大 ${d.real_max_streak || 0}连败 | 当前 ${d.real_current_streak || 0}连败（侦察不计入）`;
    }
    renderHits(d.hits);
  }
  if (desk.heatmap) renderHeat(desk.heatmap, desk.recommended, desk.zones);
  const prog = st.progress || {};
  if (st.running && prog.last) renderLast(prog.last);
  if (st.running) {
    if (prog.soul && $("soul-note")) $("soul-note").textContent = prog.soul.note || "";
    if (prog.probe_work) {
      $("progress").textContent = `分析探针还剩 ${prog.probe_work} 局 · ${prog.phase || ""} · 不下实战`;
    } else if (prog.resting) {
      const left = prog.rest_left || 0;
      const mm = Math.floor(left / 60);
      const ss = left % 60;
      $("progress").textContent = `灵魂歇着 ${mm}分${ss}秒 · ${prog.rest_why || prog.rotate_reason || "收口"} · 到点自己再开`;
    } else if (prog.loop_sessions) {
      const rot = prog.rotate_reason ? `上一轮：${prog.rotate_reason} · ` : "";
      $("progress").textContent =
        `托管 第 ${prog.session_index || 1} 轮 ${rot}` +
        `本轮 ${prog.session_rounds || 0}/${prog.session_cap || 200} · ${money(prog.session_profit, true)}` +
        (prog.last ? ` · #${prog.last.n || ""} ${Number(prog.last.profit) >= 0 ? "WIN" : "LOSS"}` : "");
    } else {
      $("progress").textContent = `运行中 ${prog.completed || 0}/${prog.total || 0} · ${prog.last ? ("#" + (prog.last.n || "") + " " + (Number(prog.last.profit) >= 0 ? "WIN" : "LOSS")) : ""}`;
    }
  } else if (!liveJobId) $("progress").textContent = prog.stop_reason || "就绪";
  if (st.preview) renderPreview(st.preview);
  renderStage(st.preview || lastPreview, st);
}

let pnlState = { range: "today", from: "", to: "", data: null };

function shiftYmd(ymd, days) {
  const p = (ymd || todayYmd()).split("-").map(Number);
  const d = new Date(p[0], p[1] - 1, p[2]);
  d.setDate(d.getDate() + days);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}
function pctRoi(roi) {
  const n = Number(roi) * 100;
  if (!isFinite(n)) return "—";
  const s = n.toFixed(2) + "%";
  return n > 0 ? "+" + s : s;
}
function sumDays(days, from, to) {
  const b = { profit: 0, staked: 0, returned: 0, rounds: 0, wins: 0, fails: 0 };
  (days || []).forEach((d) => {
    if (from && d.day < from) return;
    if (to && d.day > to) return;
    b.profit += Number(d.profit || 0);
    b.staked += Number(d.staked || 0);
    b.returned += Number(d.returned || 0);
    b.rounds += Number(d.rounds || 0);
    b.wins += Number(d.wins || 0);
    b.fails += Number(d.fails || 0);
  });
  b.roi = b.staked ? b.profit / b.staked : 0;
  return b;
}
function pnlRangeBounds(data) {
  const today = (data && data.today) || todayYmd();
  const range = pnlState.range || "today";
  if (range === "today") return { from: today, to: today, label: "今天" };
  if (range === "d7") return { from: shiftYmd(today, -6), to: today, label: "近7天" };
  if (range === "d30") return { from: shiftYmd(today, -29), to: today, label: "近30天" };
  const from = ($("pnl-from") && $("pnl-from").value) || pnlState.from || today;
  const to = ($("pnl-to") && $("pnl-to").value) || pnlState.to || today;
  return { from, to, label: from + " ~ " + to };
}
function renderPnlChart(el, pts, title) {
  if (!el) return;
  if (!pts || !pts.length) {
    el.innerHTML = `<p class="hint">这个区间还没有局</p>`;
    return;
  }
  const w = 880, h = 240, padL = 58, padR = 18, padT = 18, padB = 32;
  const ys = pts.map((p) => Number(p.cum));
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(0, ...ys);
  const spanY = maxY - minY || 1;
  const n = pts.length;
  const xAt = (i) => padL + (i / Math.max(n - 1, 1)) * (w - padL - padR);
  const yAt = (v) => padT + (1 - (v - minY) / spanY) * (h - padT - padB);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(Number(p.cum)).toFixed(1)}`).join(" ");
  const zero = yAt(0);
  const last = ys[ys.length - 1];
  const color = last >= 0 ? "#34d399" : "#f87171";
  const area = `M${xAt(0).toFixed(1)},${zero.toFixed(1)} ${pts.map((p, i) => `L${xAt(i).toFixed(1)},${yAt(Number(p.cum)).toFixed(1)}`).join(" ")} L${xAt(n - 1).toFixed(1)},${zero.toFixed(1)} Z`;
  const firstLab = pts[0].label || "";
  const lastLab = pts[n - 1].label || "";
  el.innerHTML =
    `<div class="equity-meta">${title || ""}　累计 ${money(last, true)}</div>` +
    `<svg viewBox="0 0 ${w} ${h}" class="equity-svg" preserveAspectRatio="none">` +
    `<line x1="${padL}" x2="${w - padR}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" class="eq-zero"/>` +
    `<path class="eq-fill" d="${area}" fill="${color}"/>` +
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="2"/>` +
    `<text class="eq-lab" x="${padL}" y="${h - 8}">${firstLab}</text>` +
    `<text class="eq-lab" x="${w - padR - 72}" y="${h - 8}">${lastLab}</text>` +
    `</svg>`;
}
function bindPnlBoard() {
  const chips = $("pnl-chips");
  if (!chips || chips._bound) return;
  chips._bound = true;
  const today = todayYmd();
  if ($("pnl-from") && !$("pnl-from").value) $("pnl-from").value = today;
  if ($("pnl-to") && !$("pnl-to").value) $("pnl-to").value = today;
  chips.querySelectorAll("button[data-pnl]").forEach((btn) => {
    btn.onclick = () => {
      pnlState.range = btn.getAttribute("data-pnl") || "today";
      if (pnlState.data) renderPnlBoard(pnlState.data);
    };
  });
  ["pnl-from", "pnl-to"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.onchange = () => {
      let from = $("pnl-from").value;
      let to = $("pnl-to").value;
      if (from && to && from > to) {
        const tmp = from; from = to; to = tmp;
        $("pnl-from").value = from;
        $("pnl-to").value = to;
      }
      pnlState.range = "custom";
      pnlState.from = from;
      pnlState.to = to;
      if (pnlState.data) renderPnlBoard(pnlState.data);
    };
  });
}
function rebaseCurve(src, from, to) {
  const slice = (src || []).filter((p) => {
    const day = String(p.ts || "").slice(0, 10);
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  });
  if (!slice.length) return [];
  const base = Number(slice[0].cum) - Number(slice[0].profit || 0);
  return slice.map((p) => ({ ts: p.ts, cum: Number(p.cum) - base, profit: p.profit }));
}
function pointsForPnl(data, range, bounds) {
  if (range === "today") return { raw: data.today_curve || [], labelFn: (p) => String(p.ts || "").slice(11, 16) };
  if (range === "d7") return { raw: data.d7_curve || [], labelFn: (p) => String(p.ts || "").slice(5, 16) };
  if (range === "d30") return { raw: data.d30_curve || [], labelFn: (p) => String(p.ts || "").slice(5, 16) };
  const from = bounds.from, to = bounds.to;
  if (from && to && from === to && from === data.today) {
    return { raw: data.today_curve || [], labelFn: (p) => String(p.ts || "").slice(11, 16) };
  }
  const src = (data.d30_curve && data.d30_curve.length) ? data.d30_curve : (data.d7_curve || []);
  const raw = rebaseCurve(src, from, to);
  if (raw.length) return { raw, labelFn: (p) => String(p.ts || "").slice(5, 16) };
  const slice = (data.days || []).filter((d) => (!from || d.day >= from) && (!to || d.day <= to));
  let run = 0;
  return {
    raw: slice.map((d) => { run += Number(d.profit || 0); return { ts: d.day, cum: run }; }),
    labelFn: (p) => String(p.ts || "").slice(5),
  };
}
function renderPnlBoard(data) {
  pnlState.data = data;
  bindPnlBoard();
  const buckets = data.buckets || {};
  const days = data.days || [];
  const bounds = pnlRangeBounds(data);
  const custom = sumDays(days, bounds.from, bounds.to);
  const boxDefs = [
    ["today", "今天", buckets.today],
    ["d7", "近7天", buckets.d7],
    ["d30", "近30天", buckets.d30],
    ["custom", "自选区间", custom],
  ];
  const boxes = $("pnl-boxes");
  if (boxes) {
    boxes.innerHTML = boxDefs.map(([key, title, b]) => {
      const bag = b || {};
      const on = pnlState.range === key ? " on" : "";
      const sub = key === "custom" && bounds.from && bounds.to ? `${bounds.from} ~ ${bounds.to}` : "";
      return `<button type="button" class="pnl-box${on}" data-pnl="${key}">` +
        `<div class="ttl">${title}${sub ? `<span class="sub"> ${sub}</span>` : ""}</div>` +
        `<div class="v ${clsP(bag.profit)}">${money(bag.profit, true)}</div>` +
        `<div class="io"><span>投资金<b>${money(bag.staked)}</b></span><span>回收金<b>${money(bag.returned)}</b></span></div>` +
        `<div class="s">收益率 ${pctRoi(bag.roi)} · ${bag.rounds || 0} 局</div>` +
        `</button>`;
    }).join("");
    boxes.querySelectorAll("button[data-pnl]").forEach((btn) => {
      btn.onclick = () => {
        pnlState.range = btn.getAttribute("data-pnl") || "today";
        renderPnlBoard(data);
      };
    });
  }
  document.querySelectorAll("#pnl-chips button[data-pnl]").forEach((btn) => {
    btn.classList.toggle("on", btn.getAttribute("data-pnl") === pnlState.range);
  });
  const selected = pnlState.range === "custom" ? custom : (buckets[pnlState.range] || custom);
  const kpis = $("pnl-kpis");
  if (kpis) {
    const wr = selected.rounds ? ((Number(selected.wins || 0) / selected.rounds) * 100).toFixed(1) + "%" : "—";
    const cells = [
      [money(selected.staked), "投资金", ""],
      [money(selected.returned), "回收金", ""],
      [pctRoi(selected.roi), "收益率", clsP(selected.profit)],
      [selected.rounds || 0, "局数", ""],
      [wr, "成功率", ""],
    ];
    kpis.innerHTML = cells.map((c) =>
      `<div class="mh"><div class="v ${c[2]}">${c[0]}</div><div class="k">${c[1]}</div></div>`
    ).join("");
  }
  const picked = pointsForPnl(data, pnlState.range, bounds);
  const pts = (picked.raw || []).map((p) => ({ cum: Number(p.cum), label: picked.labelFn(p) }));
  const title = `${bounds.label} · ${pts.length ? pts[0].label : "—"} → ${pts.length ? pts[pts.length - 1].label : "—"} · ${selected.rounds || 0}局`;
  renderPnlChart($("pnl-chart"), pts, title);
}

async function loadAll() {
  const st = await api("/api/live/status");
  renderStatus(st);
  const sess = await api("/api/history?book=live&scope=session&limit=500");
  histAllRows = sess.records || [];
  paintHist();
  if ((sess.records || [])[0]) renderLast(sess.records[0]);
  const runs = await api("/api/live/runs");
  allRuns = runs.runs || [];
  bindRunFilters();
  fillStrategySelect(allRuns);
  applyRunFilters(true);
  const cur = st.current_run;
  if (cur) {
    $("current-run-label").textContent = (cur.name || "当前") + (cur.open ? " · 进行中" : "");
    if (cur.name && !$("run-name").value) $("run-name").value = cur.name;
  }
  const pnl = await api("/api/live/pnl");
  if (pnl && pnl.ok !== false && pnl.buckets && (pnl.today_curve || pnl.d7_curve)) {
    renderPnlBoard(pnl);
    return;
  }
  const life = await api("/api/history?book=live&scope=lifetime&limit=20000");
  renderPnlBoard(pnlFromRecordRows(life.records || []));
}

function _downsampleJs(points, maxPoints) {
  const n = points.length;
  if (n <= maxPoints) return points;
  const out = [];
  for (let i = 0; i < maxPoints - 1; i++) {
    out.push(points[Math.floor(i * (n - 1) / (maxPoints - 1))]);
  }
  out.push(points[n - 1]);
  return out;
}
function pnlFromRecordRows(records) {
  const today = todayYmd();
  const start7 = shiftYmd(today, -6);
  const start30 = shiftYmd(today, -29);
  const ordered = [...(records || [])]
    .filter((r) => String(r.ts || "").length >= 10)
    .sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  const byDay = {};
  const pack = (b) => ({
    profit: b.profit,
    staked: b.staked,
    returned: b.returned,
    rounds: b.rounds,
    wins: b.wins,
    fails: b.fails,
    roi: b.staked ? b.profit / b.staked : 0,
  });
  const empty = () => ({ profit: 0, staked: 0, returned: 0, rounds: 0, wins: 0, fails: 0 });
  const add = (b, r) => {
    const bet = Number(r.bet || 0);
    const payout = Number(r.payout || 0);
    const profit = r.profit == null || r.profit === "" ? payout - bet : Number(r.profit);
    b.profit += profit;
    b.staked += bet;
    b.returned += payout;
    b.rounds += 1;
    if (payout >= bet) b.wins += 1;
    else b.fails += 1;
    return profit;
  };
  const todayB = empty();
  const d7B = empty();
  const d30B = empty();
  const allB = empty();
  const todayCurve = [];
  const d7Curve = [];
  const d30Curve = [];
  let todayCum = 0, d7Cum = 0, d30Cum = 0;
  ordered.forEach((r) => {
    const day = String(r.ts).slice(0, 10);
    const b = byDay[day] || empty();
    const profit = add(b, r);
    byDay[day] = b;
    add(allB, r);
    if (day === today) {
      add(todayB, r);
      todayCum += profit;
      todayCurve.push({ ts: r.ts, cum: todayCum, profit });
    }
    if (day >= start7 && day <= today) {
      add(d7B, r);
      d7Cum += profit;
      d7Curve.push({ ts: r.ts, cum: d7Cum, profit });
    }
    if (day >= start30 && day <= today) {
      add(d30B, r);
      d30Cum += profit;
      d30Curve.push({ ts: r.ts, cum: d30Cum, profit });
    }
  });
  const days = Object.keys(byDay).sort().map((day) => ({ day, ...pack(byDay[day]) }));
  let run = 0;
  days.forEach((d) => { run += Number(d.profit || 0); d.cum = run; });
  return {
    ok: true,
    today,
    buckets: { today: pack(todayB), d7: pack(d7B), d30: pack(d30B), all: pack(allB) },
    days,
    today_curve: _downsampleJs(todayCurve, 360),
    d7_curve: _downsampleJs(d7Curve, 360),
    d30_curve: _downsampleJs(d30Curve, 360),
  };
}

// One line under the toolbar so a slow login is visible instead of silent.
function setConnectBanner(st) {
  const el = $("connect-note");
  if (!el) return;
  const msg = st.error || "";
  el.textContent = msg;
  el.style.display = msg ? "block" : "none";
}

async function connect() {
  $("btn-connect").disabled = true;
  $("acct").textContent = "正在弹出 Chrome…";
  toast("正在弹出 Chrome，请在那个窗口登录 Stake", 5000);
  let lastNote = "";
  try {
    await api("/api/live/connect", "POST", { wait_login: 180 });
    const start = Date.now();
    while (Date.now() - start < 200000) {
      const st = await api("/api/live/status");
      renderStatus(st);
      const note = st.error || "";
      if (note && note !== lastNote) { lastNote = note; toast(note, 8000); }
      if (st.status === "connected") break;
      if (st.status === "error") break;
      await new Promise((r) => setTimeout(r, 1500));
    }
    await loadAll();
    await refreshPreview();
  } finally {
    $("btn-connect").disabled = false;
  }
}

async function startLive(roundsOverride, loop) {
  if (!$("live-bets").checked) { toast("先勾选允许真钱下注"); return; }
  await refreshPreview();
  const amount = Number((lastPreview && lastPreview.amount) || $("base-bet").value);
  if (amount > 0.001) {
    if (!window.confirm(`下一注 ${lastPreview.amount} USDT，确认用真钱下？`)) return;
  }
  const sessionRounds = Number($("rounds").value) || 200;
  const host = $("autohost") && $("autohost").checked;
  if (host) loop = true;
  if (loop && !host) {
    if (!window.confirm(`无限跑：每一轮 ${sessionRounds} 局。止盈或第4档赢了才新开一轮。止损或四连败会整段停。托管请勾「灵魂托管」再点开始。`)) return;
  }
  if (host) {
    if ($("after-bank")) $("after-bank").value = "rest";
    if ($("playbook")) $("playbook").checked = true;
  }
  const rounds = roundsOverride || (loop ? 0 : sessionRounds);
  const snap = payload();
  const res = await api("/api/live/run", "POST", {
    async: true,
    live_bets: true,
    new_session: false,
    playbook: snap.playbook,
    after_bank: snap.after_bank,
    session_stop_win: snap.session_stop_win,
    session_max_rounds: sessionRounds,
    daily_stop_win: snap.daily_stop_win,
    stop_on_mult: snap.stop_on_mult,
    rounds,
    session_rounds: sessionRounds,
    loop_sessions: !!loop,
    hours: 0,
    unattended: !!loop || sessionRounds > 200,
    slice_rounds: 200,
    slice_cooldown: 3,
    risk: $("risk").value,
    stop_loss: $("loss").value,
    stop_win: $("win").value,
    max_streak: $("max-streak").value,
    pace_seconds: Number($("pace").value) || 3,
    run_name: $("run-name").value.trim(),
    ...snap,
  });
  if (!res.ok) { toast(res.error || "无法启动"); return; }
  liveJobId = res.job_id;
  $("progress").textContent = "向 Stake 下单…";
  while (liveJobId) {
    const st = await api("/api/live/status");
    renderStatus(st);
    const job = await api(`/api/run/status?job_id=${encodeURIComponent(liveJobId)}`);
    if (job.status === "completed" || job.status === "cancelled" || job.status === "failed") {
      if (job.error) toast(job.error);
      if (job.result && job.result.stop_reason) $("progress").textContent = `结束 ${job.result.rounds} 局 · ${job.result.stop_reason}`;
      liveJobId = null;
      await loadAll();
      await refreshPreview();
      return;
    }
    await new Promise((r) => setTimeout(r, 800));
  }
}

$("btn-connect").onclick = connect;
$("btn-start").onclick = () => {
  if ($("autohost")) $("autohost").checked = false;
  startLive();
};
if ($("btn-host-start")) {
  $("btn-host-start").onclick = () => {
    if ($("autohost")) $("autohost").checked = true;
    if ($("after-bank")) $("after-bank").value = "rest";
    if ($("playbook")) $("playbook").checked = true;
    startLive(null, true);
  };
}
if ($("btn-host-stop")) $("btn-host-stop").onclick = async () => { await api("/api/live/stop", "POST", {}); };
if ($("btn-loop")) $("btn-loop").onclick = () => startLive(null, true);
$("btn-one").onclick = () => startLive(1);
$("btn-stop").onclick = async () => { await api("/api/live/stop", "POST", {}); };
$("btn-reset").onclick = async () => {
  const name = $("run-name").value.trim();
  await api("/api/live/reset", "POST", { name, settings: settingsSnap() });
  $("run-name").value = "";
  await loadAll();
  await refreshPreview();
  toast("已收口这一次，开始新的一次");
};
$("btn-save").onclick = async () => {
  await refreshPreview();
  await api("/api/live/runs/rename", "POST", { name: $("run-name").value.trim() });
  toast("设置已保存");
};
$("modal-close").onclick = () => $("run-modal").classList.add("hidden");
if ($("modal-export")) {
  $("modal-export").onclick = () => {
    if (!modalRunId) return;
    window.location.href = "/api/live/runs?id=" + encodeURIComponent(modalRunId) + "&export=1";
  };
}
$("run-modal").onclick = (ev) => { if (ev.target.id === "run-modal") $("run-modal").classList.add("hidden"); };
$("btn-auto-pick").onclick = async () => {
  selected = [];
  await refreshPreview();
  if (lastPreview && lastPreview.recommended) {
    selected = lastPreview.recommended.slice(0, Number($("pick-count").value) || 10).map((r) => r.n);
  } else if (lastPreview && lastPreview.picks) {
    selected = lastPreview.picks.map(Number);
  }
  renderBoard();
};
$("btn-clear").onclick = () => { selected = []; lastDrawn = []; renderBoard(); };
function autoRunName() {
  const risk = { low: "低等", medium: "中等", classic: "典型", high: "高等" }[$("risk").value] || $("risk").value;
  return (risk + " " + ($("custom-amounts").value.trim() || "")).trim();
}
function setRunName(name, auto) {
  const el = $("run-name");
  if (!el) return;
  el.value = name || "";
  el.dataset.auto = auto ? "1" : "0";
}
function syncRunName() {
  const el = $("run-name");
  if (!el) return;
  if (el.dataset.auto !== "1" && el.value.trim()) return;
  setRunName(autoRunName(), true);
}
$("risk").onchange = () => { renderPaytable($("risk").value); syncRunName(); refreshPreview(); };
if ($("run-name")) {
  $("run-name").oninput = () => { $("run-name").dataset.auto = "0"; };
}
document.querySelectorAll(".presets button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".presets button").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
    $("custom-amounts").value = btn.getAttribute("data-ladder");
    $("max-level").value = btn.getAttribute("data-max");
    $("base-bet").value = btn.getAttribute("data-ladder").split(",")[0];
    const risk = btn.getAttribute("data-risk");
    if (risk) {
      $("risk").value = risk;
      renderPaytable(risk);
    }
    const loss = btn.getAttribute("data-loss");
    if (loss !== null && loss !== undefined) $("loss").value = loss;
    if (btn.hasAttribute("data-win")) $("win").value = btn.getAttribute("data-win") || "";
    const rounds = btn.getAttribute("data-rounds");
    if (rounds) $("rounds").value = rounds;
    const streak = btn.getAttribute("data-streak");
    if (streak) $("max-streak").value = streak;
    const name = btn.getAttribute("data-name") || (btn.textContent || "").trim();
    setRunName(name, true);
    $("pick-count").value = "10";
    $("reset-max").checked = false;
    $("keep-on-win").value = "1";
    $("recon-on").value = btn.getAttribute("data-recon") || "0";
    if (btn.hasAttribute("data-recon-n-win")) $("recon-n-win").value = btn.getAttribute("data-recon-n-win");
    if (btn.hasAttribute("data-recon-n-loss")) $("recon-n-loss").value = btn.getAttribute("data-recon-n-loss");
    if (btn.hasAttribute("data-recon-real-n")) $("recon-real-n").value = btn.getAttribute("data-recon-real-n");
    if ($("recon-return-win")) $("recon-return-win").checked = btn.getAttribute("data-recon-return") === "1";
    if ($("recon-abort-loss")) $("recon-abort-loss").checked = btn.getAttribute("data-recon-abort") === "1";
    if ($("stop-max-win")) $("stop-max-win").checked = btn.getAttribute("data-stop-max-win") !== "0";
    if ($("playbook")) $("playbook").checked = btn.getAttribute("data-playbook") === "1";
    if ($("after-bank") && btn.hasAttribute("data-after-bank")) $("after-bank").value = btn.getAttribute("data-after-bank");
    if ($("daily-win") && btn.hasAttribute("data-daily")) $("daily-win").value = btn.getAttribute("data-daily") || "";
    if ($("daily-loss") && btn.hasAttribute("data-daily-loss")) $("daily-loss").value = btn.getAttribute("data-daily-loss") || "";
    if ($("fat-mult") && btn.hasAttribute("data-fat")) $("fat-mult").value = btn.getAttribute("data-fat") || "8";
    if ($("autohost") && btn.hasAttribute("data-autohost")) $("autohost").checked = btn.getAttribute("data-autohost") === "1";
    if ($("recon-abort-after") && btn.hasAttribute("data-recon-abort-after")) $("recon-abort-after").value = btn.getAttribute("data-recon-abort-after");
    if ($("rest-seconds") && btn.hasAttribute("data-rest")) $("rest-seconds").value = btn.getAttribute("data-rest");
    if ($("hard-rest-seconds") && btn.hasAttribute("data-hard-rest")) $("hard-rest-seconds").value = btn.getAttribute("data-hard-rest");
    const note = btn.getAttribute("data-toast");
    if (note) toast(note, 6500);
    refreshPreview();
  };
});
["custom-amounts", "start-level", "max-level", "keep-on-win", "recon-on", "pick-count", "base-bet"].forEach((id) => {
  $(id).onchange = () => { if (id === "custom-amounts") syncRunName(); refreshPreview(); };
});
if ($("autohost")) {
  $("autohost").onchange = () => {
    if ($("autohost").checked) {
      if ($("after-bank")) $("after-bank").value = "rest";
      if ($("playbook")) $("playbook").checked = true;
    }
  };
}

renderBoard();
refreshPreview().then(loadAll);
setInterval(loadAll, 3000);
