"use strict";
const $ = (id) => document.getElementById(id);

let selected = new Set();
let currentDrawn = [];
let lastState = null;
let revealLock = false;
let betBusy = false;
let lastHits = null;
let labJobId = null;
let autoJobId = null;

async function api(path, method = "GET", body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    return { ok: false, error: "无法连接本地服务（请再双击根目录 启动.bat）" };
  }
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch (err) {
    return { ok: false, error: `服务返回异常（HTTP ${res.status}）` };
  }
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3000);
}

const fmtPct = (x) => (x * 100).toFixed(1) + "%";
const clsProfit = (v) => { const n = Number(v); return n > 0 ? "pos" : (n < 0 ? "neg" : ""); };
const signed = (v) => { const n = Number(v); return (n > 0 ? "+" : "") + v; };
function fmtDur(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return `${h}小时 ${m}分 ${s}秒`;
}

function fmtUsd(v, withSign) {
  const n = Number(v);
  const mag = "$" + Math.abs(n).toFixed(4);
  if (n < 0) return "-" + mag;
  if (withSign && n > 0) return "+" + mag;
  return mag;
}

function renderBoard() {
  const drawn = new Set(currentDrawn.map(Number));
  const board = $("board");
  board.innerHTML = "";
  for (let n = 1; n <= 40; n++) {
    const b = document.createElement("button");
    b.textContent = n;
    if (drawn.has(n)) {
      b.classList.add(selected.has(n) ? "hit" : "draw");
    } else if (selected.has(n)) {
      b.classList.add("sel");
    }
    b.onclick = () => {
      if (revealLock) return;
      if (selected.has(n)) selected.delete(n);
      else if (selected.size < 10) selected.add(n);
      renderBoard();
      updateStatus();
      updateBetState();
    };
    board.appendChild(b);
  }
}

function updateStatus() {
  const el = $("status-line");
  if (el) {
    if (selected.size > 0) {
      el.innerHTML = `已选 <b>${selected.size}</b> 个数字 · 点击投注`;
    } else {
      el.textContent = "请选择 1–10 个数字以开始游戏";
    }
  }
  renderPaytable(lastState);
}

function updateBetState() {
  const btn = $("btn-bet");
  if (!btn) return;
  const amt = Number($("amount").value) || 0;
  btn.disabled = revealLock || selected.size < 1 || amt <= 0;
}

function updateAmtHint() {
  const el = $("amt-hint");
  if (!el) return;
  const v = Number($("amount").value) || 0;
  el.textContent = v.toFixed(2) + " 美元";
}

function flashStatus(msg) {
  const el = $("status-line");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 800);
}

function fmtMult(v) {
  if (v >= 1000) return Math.round(v).toLocaleString("en-US") + "x";
  if (v >= 100) return v.toFixed(1) + "x";
  return v.toFixed(2) + "x";
}

function renderPaytable(st) {
  if (!st || !st.paytable) return;
  const rowA = $("paytable-row");
  const rowB = $("hits-row");
  if (!rowA || !rowB) return;
  const risk = $("risk").value;
  const pc = Math.min(Math.max(selected.size || 10, 1), 10);
  const table = (st.paytable[risk] || {})[String(pc)] || [];
  let a = "";
  let b = "";
  for (let h = 0; h <= pc; h++) {
    const mult = Number(table[h] || 0);
    const act = (lastHits !== null && lastHits === h) ? " active" : "";
    a += `<div class="pt-cell${act}">${fmtMult(mult)}</div>`;
    b += `<div class="pt-cell${act}">${h}x</div>`;
  }
  rowA.innerHTML = a;
  rowB.innerHTML = b;
}

function showResult(r) {
  const col = document.querySelector(".board-col");
  if (!col) return;
  const old = col.querySelector(".result-popup");
  if (old) old.remove();
  const p = Number(r.profit);
  const win = p > 0;
  const mult = Number(r.multiplier);
  const el = document.createElement("div");
  el.className = "result-popup " + (win ? "win" : "lose");
  const amt = (win ? "+" : "") + String(r.profit);
  el.innerHTML = `<div class="rp-mult">${mult.toFixed(2)}倍</div>` +
    `<div class="rp-amt">${amt} <span class="rp-coin">T</span></div>`;
  col.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 500);
  }, 3600);
}

function animateReveal(drawn, picks) {
  return new Promise((resolve) => {
    revealLock = true;
    const cells = $("board").children;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      revealLock = false;
      resolve();
    };
    if (!drawn.length) {
      finish();
      return;
    }
    drawn.forEach((n, i) => {
      setTimeout(() => {
        const b = cells[n - 1];
        if (b) {
          b.classList.add("revealing");
          if (picks.has(n)) {
            b.classList.remove("sel");
            b.classList.add("hit");
          } else {
            b.classList.add("draw");
          }
          setTimeout(() => b.classList.remove("revealing"), 420);
        }
        if (i === drawn.length - 1) {
          finish();
        }
      }, 85 * i + 40);
    });
    setTimeout(finish, 85 * drawn.length + 500);
  });
}

function renderSessionBar(st) {
  const s = st.session;
  const cells = [
    ["总收益", fmtUsd(s.profit), clsProfit(s.profit)],
    ["局数", s.rounds, ""],
    ["成功率", fmtPct(s.success_rate), ""],
    ["余额", fmtUsd(st.balance), ""],
    ["投入", fmtUsd(s.staked), ""],
    ["回收", fmtUsd(s.returned), ""],
    ["等级", st.level, ""],
    ["时长", fmtDur(st.session.duration_sec || 0), ""],
  ];
  $("session-bar").innerHTML = cells.map(([label, value, cls]) =>
    `<div class="cell"><div class="value ${cls}" data-metric="${label}">${value}</div><div class="label">${label}</div></div>`
  ).join("");
}

function renderStageTable(rows) {
  const head = `<tr><th class="left">阶段</th><th>局数</th><th>成功</th><th>失败</th><th>成功率</th><th>投注额</th><th>回收额</th><th>收益</th></tr>`;
  const body = rows.map((r) => {
    const role = r.role || "stage";
    const name = role === "subtotal" || role === "total" ? r.stage : r.stage;
    return `<tr class="role-${role}"><td class="left mono">${name}</td><td>${r.rounds}</td><td>${r.wins}</td><td>${r.fails}</td>` +
      `<td>${fmtPct(r.success_rate)}</td><td>${fmtUsd(r.staked)}</td><td>${fmtUsd(r.returned)}</td>` +
      `<td class="${clsProfit(r.profit)}">${fmtUsd(r.profit, true)}</td></tr>`;
  }).join("");
  $("stage-table").innerHTML = head + body;
}

function renderHitTable(rows) {
  const head = `<tr><th class="left">命中</th><th>局数</th><th>占比</th><th>投注额</th><th>回收额</th><th>收益</th></tr>`;
  const body = rows.map((r) =>
    `<tr><td class="left">${r.hits}中</td><td>${r.rounds}</td><td>${fmtPct(r.share)}</td>` +
    `<td>${fmtUsd(r.staked)}</td><td>${fmtUsd(r.returned)}</td>` +
    `<td class="${clsProfit(r.profit)}">${fmtUsd(r.profit, true)}</td></tr>`
  ).join("");
  $("hit-table").innerHTML = head + body;
}

function renderMonitor(st) {
  const regime = st.regime || {};
  $("regime-panel").innerHTML =
    `<div class="monitor-item"><span>当前状态</span><b>${regime.state || "NORMAL"}</b></div>` +
    `<div class="monitor-item"><span>观察窗口</span><b>${regime.window || 0} 局</b></div>` +
    `<div class="monitor-item"><span>当前连亏</span><b class="neg">${regime.loss_streak || 0}</b></div>` +
    `<div class="monitor-item"><span>当前连胜</span><b class="pos">${regime.win_streak || 0}</b></div>` +
    `<div class="monitor-item"><span>风险动作</span><b>${regime.recommended_action || "continue"}</b></div>`;
  const matrix = st.theory_matrix || {};
  const currentRisk = $("risk").value;
  const currentPickCount = Math.min(Math.max(selected.size || 10, 1), 10);
  const currentTheory = matrix[currentRisk] && matrix[currentRisk][String(currentPickCount)];
  $("theory-panel").innerHTML = currentTheory
    ? `当前基线：${currentRisk} + ${currentPickCount} 选 · RTP <b>${Number(currentTheory.rtp_pct).toFixed(4)}%</b> · ` +
      `理论 ROI <b class="${clsProfit(currentTheory.expected_roi_pct)}">${Number(currentTheory.expected_roi_pct).toFixed(4)}%</b> · ` +
      `<span>盈利局概率 ${Number(currentTheory.profit_probability_pct).toFixed(2)}%</span>`
    : "";
  const blocks = st.block_table || [];
  const head = `<tr><th>15分钟块</th><th>局号</th><th>局数</th><th>投入</th><th>收益</th><th>ROI</th></tr>`;
  const body = blocks.slice(-12).map((row) =>
    `<tr><td>${row.block}</td><td>${row.round_start}-${row.round_end}</td><td>${row.rounds}</td>` +
    `<td>${row.staked}</td><td class="${clsProfit(row.profit)}">${signed(row.profit)}</td>` +
    `<td class="${clsProfit(row.roi_pct)}">${Number(row.roi_pct).toFixed(2)}%</td></tr>`
  ).join("");
  $("block-table").innerHTML = blocks.length ? head + body : "";
}

function colorList(nums, win) {
  const cls = win ? "n-hit" : "n-miss";
  return `[${(nums || []).map((n) => `<span class="${cls}">${n}</span>`).join(",")}]`;
}

function historyTable(rows) {
  const head = `<tr><th>账本</th><th>会话</th><th>#</th><th>投注</th><th class="left">选号</th><th class="left">开奖</th>` +
    `<th>命中</th><th>倍数</th><th>盈亏</th></tr>`;
  const body = (rows || []).map((r) => {
    const win = Number(r.payout) > Number(r.bet);
    const probe = r.probe || (String(r.stage || "").indexOf("探针") >= 0);
    const id = probe ? `${r.id} <span class="probe-tag">[探针]</span>` : String(r.id);
    const betCls = win ? "pos" : "neg";
    const book = r.book === "live" ? "实盘" : "虚拟盘";
    return `<tr class="${win ? "row-win" : "row-lose"}"><td>${book}</td><td>${r.session || ""}</td><td class="left">${id}</td>` +
      `<td class="${betCls}">${fmtUsd(r.bet)}</td>` +
      `<td class="left mono">${colorList(r.picks, win)}</td>` +
      `<td class="left mono">${colorList(r.drawn, win)}</td>` +
      `<td>${r.hits}</td><td>x${Number(r.multiplier).toFixed(2)}</td>` +
      `<td class="${clsProfit(r.profit)}">${fmtUsd(r.profit, true)}</td></tr>`;
  }).join("");
  return head + body;
}

async function refreshHistory() {
  const sess = await api("/api/history?book=paper&scope=session&limit=80");
  $("history").innerHTML = historyTable(sess.records || []);
  const life = $("history-lifetime");
  if (life) {
    const all = await api("/api/history?book=paper&scope=lifetime&limit=120");
    life.innerHTML = historyTable(all.records || []);
  }
}

function applyState(st) {
  const previousBalance = lastState && lastState.balance;
  lastState = st;
  renderSessionBar(st);
  if (previousBalance !== undefined && previousBalance !== st.balance) {
    const balanceCell = document.querySelector('[data-metric="余额"]');
    if (balanceCell) {
      balanceCell.classList.add(Number(st.balance) >= Number(previousBalance) ? "balance-up" : "balance-down");
      setTimeout(() => balanceCell.classList.remove("balance-up", "balance-down"), 700);
    }
  }
  renderStageTable(st.stage_table || []);
  renderHitTable(st.hit_table || []);
  renderMonitor(st);
  renderBoard();
  renderPaytable(st);
  const ae = document.activeElement;
  if (ae !== $("client-seed")) $("client-seed").value = st.client_seed;
  $("hash").textContent = st.server_seed_hash;
  $("nonce").textContent = st.nonce;
  if (ae !== $("rot-rounds")) $("rot-rounds").value = (st.auto_rotate || {}).rounds || 0;
  if (ae !== $("rot-minutes")) $("rot-minutes").value = (st.auto_rotate || {}).minutes || 0;
  const rev = (st.revealed || []).map((r) =>
    `<div class="rev">[${r.rotated_at}] 已揭示种子 · hash ${r.server_seed_hash.slice(0, 12)}… · nonce ${r.nonce_start}-${r.nonce_end} · client ${r.client_seed}</div>`
  ).join("");
  $("revealed").innerHTML = rev || "暂无已揭示的旧种子（点「轮换并揭示」解锁历史验证）";
}

async function loadState() {
  const st = await api("/api/state");
  applyState(st);
}

async function placeBet() {
  if (revealLock || betBusy) return;
  const picks = [...selected].sort((a, b) => a - b);
  if (!picks.length) { flashStatus("先选号（1–10 个）"); return; }
  const amount = $("amount").value.trim();
  const amtNum = Number(amount);
  if (!amount || !isFinite(amtNum) || amtNum <= 0) { flashStatus("投注额无效，请输入金额"); return; }
  if (amtNum < 0.0001) { flashStatus("低于平台最低投注 0.0001"); return; }
  const risk = $("risk").value;
  betBusy = true;
  $("btn-bet").disabled = true;
  try {
    const res = await api("/api/bet", "POST", { picks, risk, amount });
    if (!res.ok) { toast(res.error || "投注失败"); return; }
    const r = res.record;
    currentDrawn = r.drawn;
    await animateReveal(r.drawn, new Set(picks));
    const p = Number(r.profit);
    $("status-line").innerHTML =
      `命中 <b>${r.hits}</b> · x${String(r.multiplier).replace(/\.0+$/, "")} · ` +
      `<span class="${p > 0 ? "win" : (p < 0 ? "lose" : "")}">${signed(r.profit)}</span>`;
    lastHits = r.hits;
    showResult(r);
    applyState(res.state);
    refreshHistory();
  } finally {
    betBusy = false;
    updateBetState();
  }
}

let lastAutoRecordId = null;

function renderSessionLog(sessions) {
  const box = $("session-log");
  if (!box) return;
  if (!sessions || !sessions.length) {
    box.innerHTML = "";
    return;
  }
  const head = `<div class="log-title">本轮自动会话</div><table><tr><th>等级</th><th>局数</th><th>投入</th><th>收益</th><th>成功率</th><th class="left">停止</th></tr>`;
  const body = sessions.map((s) =>
    `<tr><td>${s.level}</td><td>${s.rounds}</td><td>${fmtUsd(s.staked)}</td>` +
    `<td class="${clsProfit(s.profit)}">${fmtUsd(s.profit, true)}</td>` +
    `<td>${fmtPct(s.success_rate)}</td><td class="left">${s.stop_reason}</td></tr>`
  ).join("");
  box.innerHTML = head + body + "</table>";
}

async function applyLiveRound(record) {
  if (!record || record.id === lastAutoRecordId) return;
  lastAutoRecordId = record.id;
  selected = new Set(record.picks || []);
  currentDrawn = [];
  renderBoard();
  await animateReveal(record.drawn || [], selected);
  currentDrawn = record.drawn || [];
  lastHits = record.hits;
  const p = Number(record.profit);
  $("status-line").innerHTML =
    `${record.stage || ""} · 命中 <b>${record.hits}</b> · x${Number(record.multiplier).toFixed(2)} · ` +
    `<span class="${p > 0 ? "win" : (p < 0 ? "lose" : "")}">${fmtUsd(record.profit, true)}</span>`;
  showResult(record);
}

async function runAuto() {
  const pace = Number($("auto-pace").value) || 3.5;
  const unattended = $("auto-unattended").checked;
  const body = {
    kind: $("auto-kind").value,
    picks: $("auto-picks").value,
    rounds: Number($("auto-rounds").value) || 176,
    base_bet: $("auto-base").value.trim() || "0.01",
    session_bankroll: $("auto-bankroll").value.trim() || "10",
    risk: $("auto-risk").value,
    pick_count: Math.min(Math.max(Number($("auto-pick-count").value) || 10, 1), 10),
    pace_seconds: pace,
    block_rounds: Number($("auto-block").value) || Math.max(1, Math.round(15 * 60 / pace)),
    realtime: $("auto-realtime").checked,
    unattended,
    hours: unattended ? Number($("auto-hours").value || 0) : 0,
    max_sessions: Number($("auto-max-sessions").value) || 0,
  };
  const win = $("auto-win").value.trim();
  const loss = $("auto-loss").value.trim();
  if (win) body.stop_win = win;
  if (loss) body.stop_loss = loss;
  const dd = $("auto-dd").value.trim();
  if (dd) body.max_drawdown = dd;
  const daily = $("auto-daily-loss").value.trim();
  if (daily) body.daily_loss_limit = daily;
  const btn = $("btn-auto");
  const cancelBtn = $("btn-auto-cancel");
  btn.disabled = true;
  cancelBtn.disabled = false;
  btn.textContent = "运行中…";
  lastAutoRecordId = null;
  $("auto-progress").textContent = "正在启动全自动…";
  try {
    const res = await api("/api/auto", "POST", { ...body, async: true });
    if (!res.ok) { toast(res.error || "自动运行失败"); return; }
    autoJobId = res.job_id;
    const finished = await pollAutoJob();
    if (!finished || !finished.result) return;
    const s = finished.result;
    currentDrawn = [];
    lastHits = null;
    const state = await api("/api/state");
    applyState(state);
    renderSessionLog(s.sessions);
    const extra = s.unattended
      ? ` · ${s.session_count} 个会话 · 绿会话 ${s.green_sessions}`
      : "";
    $("status-line").innerHTML =
      `自动完成 ${s.level}：${s.rounds} 局${extra} · 收益 <span class="${clsProfit(s.profit)}">${fmtUsd(s.profit, true)}</span> · ` +
      `投入 ${fmtUsd(s.staked)} · 回收 ${fmtUsd(s.returned)} · 成功率 ${fmtPct(s.success_rate)} · 停止：${s.stop_reason}`;
    refreshHistory();
  } finally {
    autoJobId = null;
    btn.disabled = false;
    cancelBtn.disabled = true;
    btn.textContent = "开始全自动";
    $("auto-progress").textContent = "未运行 · 默认：低等 10 选 · 阶段机 · 探针 0.0001";
  }
}

async function pollAutoJob() {
  while (autoJobId) {
    const res = await api(`/api/run/status?job_id=${encodeURIComponent(autoJobId)}`);
    if (res.ok === false || !res.status) throw new Error(res.error || "自动运行状态读取失败");
    const pct = res.total ? (res.completed / res.total * 100).toFixed(1) : "0.0";
    const last = res.last_record;
    $("auto-progress").textContent = last
      ? `已完成 ${res.completed}/${res.total}（${pct}%） · ${last.stage} · ` +
        `下注 ${fmtUsd(last.bet)} · 收益 ${fmtUsd(last.profit, true)} · 余额 ${fmtUsd(last.balance_after)}`
      : `已完成 ${res.completed}/${res.total}（${pct}%）`;
    if (last) {
      await applyLiveRound(last);
    }
    const state = await api("/api/state");
    if (state && state.session) applyState(state);
    await refreshHistory();
    if (res.status === "completed" || res.status === "cancelled") {
      if (res.result && res.result.sessions) renderSessionLog(res.result.sessions);
      if (res.status === "cancelled") toast("自动运行已停止");
      return res;
    }
    if (res.status === "failed") throw new Error(res.error || "自动运行失败");
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  return null;
}

async function runLab() {
  const sessions = Math.min(Math.max(Number($("lab-sessions").value) || 0, 10), 20000);
  const rounds = Math.min(Math.max(Number($("lab-rounds").value) || 0, 20), 2000);
  const pickCount = Math.min(Math.max(Number($("lab-pick-count").value) || 0, 1), 10);
  if (!sessions || !rounds || !pickCount) {
    toast("实验参数无效：会话数≥10、每会话局数≥20、选号数为1–10");
    return;
  }
  const kinds = [];
  if ($("lab-flat-min").checked) kinds.push("flat-min");
  if ($("lab-flat-001").checked) kinds.push("flat-001");
  if ($("lab-fractional").checked) kinds.push("fractional");
  if ($("lab-adaptive").checked) kinds.push("adaptive");
  if ($("lab-probe").checked) kinds.push("probe-window");
  if ($("lab-capped").checked) kinds.push("capped-recovery");
  if ($("lab-phase").checked) kinds.push("phase");
  if ($("lab-mart").checked) kinds.push("martingale");
  if (!kinds.length) { toast("至少勾选一个策略"); return; }
  const btn = $("btn-lab");
  const cancelBtn = $("btn-lab-cancel");
  btn.disabled = true;
  cancelBtn.disabled = false;
  btn.textContent = "运行中…";
  try {
    const res = await api("/api/lab", "POST", {
      async: true,
      sessions,
      rounds,
      risk: $("lab-risk").value,
      pick_count: pickCount,
      pace_seconds: Number($("lab-pace").value) || 3.5,
      selection_modes: [$("lab-selection-mode").value],
      kinds,
    });
    if (!res.ok) { toast(res.error || "实验室运行失败"); return; }
    labJobId = res.job_id;
    await pollLabJob();
  } finally {
    labJobId = null;
    btn.disabled = false;
    cancelBtn.disabled = true;
    btn.textContent = "运行对照";
  }
}

function renderLabResult(res) {
  $("lab-note").textContent =
    `${res.sessions} 会话 × ${res.rounds} 局 · ${res.risk} 风险 · pick ${res.pick_count} · ` +
    `${res.pace_seconds}s/局 —— ${res.note}`;
  $("lab-sessions").value = res.sessions;
  $("lab-rounds").value = res.rounds;
  $("lab-pick-count").value = res.pick_count;
  const head = `<tr><th class="left">策略</th><th>总投注</th><th>总收益</th><th>ROI</th><th>ROI 95% CI半宽</th>` +
    `<th>绿色率</th><th>爆仓率</th><th>中位收益</th><th>平均回撤</th><th>中位存活</th></tr>`;
  const body = res.rows.map((r) =>
    `<tr><td class="left">${r.name}<br><small>${r.description}</small></td>` +
    `<td>${r.total_staked}</td><td class="${clsProfit(r.total_profit)}">${signed(r.total_profit)}</td>` +
    `<td class="${clsProfit(r.mean_roi_pct)}">${r.mean_roi_pct.toFixed(3)}%</td>` +
    `<td>+/-${r.roi_ci95_pct.toFixed(3)}%</td><td>${fmtPct(r.green_pct)}</td>` +
    `<td>${fmtPct(r.ruin_pct)}</td><td>${r.median_profit}</td><td>${r.mean_max_drawdown}</td>` +
    `<td>${Number(r.median_hours).toFixed(2)}h</td></tr>`
  ).join("");
  $("lab-table").innerHTML = head + body;
}

async function pollLabJob() {
  while (labJobId) {
    const res = await api(`/api/run/status?job_id=${encodeURIComponent(labJobId)}`);
    if (res.ok === false || !res.status) throw new Error(res.error || "实验状态读取失败");
    const pct = res.total ? (res.completed / res.total * 100).toFixed(1) : "0.0";
    $("lab-note").textContent = `实验运行中：${res.completed}/${res.total} 会话（${pct}%）`;
    if (res.status === "completed" || res.status === "cancelled") {
      if (res.result) renderLabResult(res.result);
      if (res.status === "cancelled") toast("实验已停止，已保留已完成部分");
      return;
    }
    if (res.status === "failed") throw new Error(res.error || "实验失败");
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
}

function bind() {
  $("btn-bet").onclick = placeBet;
  document.addEventListener("keydown", (e) => {
    const t = e.target || {};
    if (e.key === "Enter" && (t.tagName !== "INPUT" || t.id === "amount")) placeBet();
  });
  $("btn-clear").onclick = () => {
    if (revealLock) return;
    selected = new Set();
    currentDrawn = [];
    renderBoard();
    updateStatus();
    updateBetState();
  };
  $("btn-random").onclick = () => {
    if (revealLock) return;
    selected = new Set();
    while (selected.size < 10) selected.add(1 + Math.floor(Math.random() * 40));
    renderBoard();
    updateStatus();
    updateBetState();
  };
  $("amount").addEventListener("input", () => { updateAmtHint(); updateBetState(); });
  $("btn-half").onclick = () => {
    const v = Math.max(0.0001, (Number($("amount").value) || 0.0001) / 2);
    $("amount").value = v.toFixed(8);
    updateAmtHint();
    updateBetState();
  };
  $("btn-double").onclick = () => {
    const v = Math.max(0.0001, (Number($("amount").value) || 0.0001) * 2);
    $("amount").value = v.toFixed(8);
    updateAmtHint();
    updateBetState();
  };
  document.querySelectorAll(".tab").forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
      $("tab-manual").classList.toggle("hidden", t.dataset.tab !== "manual");
      $("tab-auto").classList.toggle("hidden", t.dataset.tab !== "auto");
    };
  });
  $("btn-fullscreen").onclick = () => {
    const el = document.querySelector(".game");
    if (document.fullscreenElement) document.exitFullscreen();
    else if (el && el.requestFullscreen) el.requestFullscreen();
  };
  $("btn-jump-stats").onclick = () => {
    const el = $("stage-table");
    if (el) el.closest(".card").scrollIntoView({ behavior: "smooth", block: "center" });
  };
  $("btn-fairness").onclick = () => {
    const el = $("client-seed");
    if (!el) return;
    const card = el.closest(".card");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("flash-card");
    setTimeout(() => card.classList.remove("flash-card"), 1600);
  };
  $("btn-auto").onclick = runAuto;
  $("btn-auto-cancel").onclick = async () => {
    if (!autoJobId) return;
    await api("/api/run/cancel", "POST", { job_id: autoJobId });
  };
  $("btn-lab").onclick = runLab;
  $("btn-lab-cancel").onclick = async () => {
    if (!labJobId) return;
    await api("/api/run/cancel", "POST", { job_id: labJobId });
  };
  $("btn-export").onclick = () => window.open("/api/export", "_blank");
  $("btn-new-session").onclick = async () => { const res = await api("/api/session/new", "POST", {}); applyState(res.state); toast("已开新会话 " + res.state.level); };
  $("btn-new-batch").onclick = async () => { const res = await api("/api/session/new", "POST", { new_batch: true }); applyState(res.state); toast("已开新批次 " + res.state.level); };
  $("btn-rotate").onclick = async () => {
    const res = await api("/api/rotate", "POST", { client_seed: $("client-seed").value.trim() });
    if (!res.ok) { toast(res.error || "失败"); return; }
    applyState(res.state);
    toast("已揭示旧服务器种子（hash " + res.revealed.server_seed_hash.slice(0, 10) + "…）并启用新配对");
  };
  $("btn-verify").onclick = async () => {
    const res = await api("/api/verify", "POST", {});
    if (!res.ok) { toast(res.error || "失败"); return; }
    toast(`验证 ${res.passed}/${res.checked} 通过` + (res.failures.length ? `；失败记录: ${res.failures.join(",")}` : ""));
  };
  $("btn-calc").onclick = async () => {
    const res = await api("/api/calc", "POST", {
      server_seed: $("calc-ss").value.trim(),
      client_seed: $("calc-cs").value.trim(),
      nonce: Number($("calc-nonce").value) || 1,
    });
    if (!res.ok) { $("calc-out").textContent = res.error || "失败"; return; }
    $("calc-out").innerHTML =
      `nonce=${res.nonce} · 0基：(${res.numbers0.join(", ")})<br>` +
      `+1 = （${res.numbers1.join(", ")}）`;
  };
  $("btn-rot-save").onclick = async () => {
    const res = await api("/api/autorotate", "POST", {
      rounds: Number($("rot-rounds").value) || 0,
      minutes: Number($("rot-minutes").value) || 0,
    });
    if (res.ok) { applyState(res.state); toast("自动轮换设置已保存"); } else { toast(res.error || "失败"); }
  };
  $("btn-selftest").onclick = async () => {
    const btn = $("btn-selftest");
    btn.disabled = true;
    btn.textContent = "检测中…";
    try {
      const res = await api("/api/selftest", "POST", { draws: 20000 });
      if (!res.ok) { toast(res.error || "失败"); return; }
      const u = res.uniformity, h = res.hits, r = res.real_rounds;
      const label = (v) => v === "PASS" ? "<b>PASS</b>" : (v === "NORMAL_RANGE" ? "正常波动(灰区)" : "<b>WARN</b>");
      $("selftest-result").innerHTML =
        `真实局复核 <b>${r.passed}/${r.checked} PASS</b>（平台采集数据逐局重算）<br>` +
        `40 号均匀性 χ²=${u.chi2}（df=${u.df}，5%临界 ${u.crit_0p05}）→ ${label(u.verdict)} · 频次 ${u.freq_min_pct}%~${u.freq_max_pct}%（期望 25%）<br>` +
        `命中分布 χ²=${h.chi2}（df=${h.df}，5%临界 ${h.crit_0p05}）→ ${label(h.verdict)}<br>` +
        `注：单次卡方在真随机下有约 5% 概率落在灰区（正常）；多跑几次应围绕 PASS 波动。`;
    } finally {
      btn.disabled = false;
      btn.textContent = "随机性自检";
    }
  };
}

setInterval(() => {
  if (lastState && lastState.session) {
    lastState.session.duration_sec = (lastState.session.duration_sec || 0) + 1;
    renderSessionBar(lastState);
  }
}, 1000);

bind();
loadState();
refreshHistory();

updateStatus();
updateBetState();
updateAmtHint();
