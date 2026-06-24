// API 基础地址
const API_BASE = "http://localhost:8000/api";

// ========== 页面状态缓存 ==========
// 缓存筛选/扫描结果，切换页面时无需重新请求
let _screeningCache = null;  // { mode, type, topn, html }
let _timingCache = null;     // { minScore, topn, html }
let _lastPage = null;        // 进入详情前所在的页面 tab 名

// ========== 页面路由 ==========
document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        const page = tab.dataset.page;
        if (page === "timing") renderTiming();
        else if (page === "screening") renderScreening();
        else if (page === "detail") renderDetail();
        else if (page === "backtest") renderBacktest();
        else if (page === "config") renderConfig();
    });
});

// ========== API 工具 ==========
async function api(path, options) {
    try {
        const res = await fetch(API_BASE + path, options || {});
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(e);
        return null;
    }
}

function formatPct(v) {
    if (v === undefined || v === null) return "-";
    const num = Number(v);
    if (isNaN(num)) return "-";
    return (num > 0 ? "+" : "") + num.toFixed(2) + "%";
}

function signalBadge(s) {
    if (!s) return "";
    if (s.includes("🌟")) return `<span class="badge badge-gold">${s}</span>`;
    if (s.includes("⛔") || s.includes("⚠️") || s.includes("🔴")) return `<span class="badge badge-red">${s}</span>`;
    if (s.includes("⚡") || s.includes("⚠️")) return `<span class="badge badge-orange">${s}</span>`;
    if (s.includes("✅") || s.includes("🟢")) return `<span class="badge badge-green">${s}</span>`;
    if (s.includes("👍")) return `<span class="badge badge-blue">${s}</span>`;
    if (s.includes("🏁")) return `<span class="badge badge-purple">${s}</span>`;
    return s;
}

function multiplierBadge(m) {
    if (m >= 2.0) return '<span class="badge badge-gold">2.0x 加倍</span>';
    if (m >= 1.5) return '<span class="badge badge-green">1.5x 增投</span>';
    if (m >= 1.0) return '<span class="badge badge-blue">1.0x 正常</span>';
    if (m >= 0.5) return '<span class="badge badge-orange">0.5x 减半</span>';
    return '<span class="badge badge-red">暂停</span>';
}

// ================================================================
//  🎯 定投决策主页（默认首页）
// ================================================================
function renderTiming() {
    const main = document.getElementById("page-content");
    const cache = _timingCache;
    const minScore = cache?.minScore || 60;
    const topn = cache?.topn || 20;
    const cachedHtml = cache?.html || "";

    main.innerHTML = `
        <div class="timing-layout">
            <!-- 左侧：定投机会扫描 -->
            <div class="timing-left">
                <div class="card">
                    <h3>🎯 定投机会扫描</h3>
                    <div class="filter-bar" style="margin-bottom:12px;">
                        <label>最小时机评分：</label>
                        <input type="number" id="timing-min-score" value="${minScore}" min="0" max="100" style="width:70px;">
                        <label>Top-N：</label>
                        <input type="number" id="timing-topn" value="${topn}" min="5" max="50" style="width:70px;">
                        <button class="btn btn-primary" onclick="scanOpportunities()">🔍 扫描机会</button>
                        ${cachedHtml ? '<span style="font-size:12px;color:#4CAF50;">（已缓存）</span>' : ''}
                        <span id="timing-status" style="font-size:12px;color:#888;"></span>
                    </div>
                    <div id="timing-results">
                        ${cachedHtml || '<div class="empty">点击"扫描机会"发现当前适合定投的指数基金</div>'}
                    </div>
                </div>
            </div>

            <!-- 右侧：单只基金诊断 + 持仓检查 -->
            <div class="timing-right">
                <div class="card" style="margin-bottom:12px;">
                    <h3>🔍 单只基金诊断</h3>
                    <div class="filter-bar" style="margin-bottom:8px;">
                        <input type="text" id="diag-code" placeholder="6位基金代码" maxlength="6" style="width:120px;">
                        <input type="number" id="diag-cost" placeholder="成本净值(可选)" step="0.0001" style="width:120px;">
                        <button class="btn btn-primary" onclick="diagnoseFund()">诊断</button>
                        <span id="diag-status" style="font-size:12px;color:#888;"></span>
                    </div>
                    <div id="diagnosis-result" style="display:none;"></div>
                </div>

                <div class="card">
                    <h3>💼 持仓诊断</h3>
                    <p style="font-size:12px;color:#888;margin-bottom:8px;">输入持仓基金代码+成本，批量诊断</p>
                    <div id="portfolio-entries">
                        <div class="portfolio-row">
                            <input type="text" class="pf-code" placeholder="基金代码" maxlength="6" style="width:100px;">
                            <input type="number" class="pf-cost" placeholder="成本净值" step="0.0001" style="width:100px;">
                            <input type="number" class="pf-shares" placeholder="份额" step="1" style="width:80px;">
                        </div>
                    </div>
                    <div style="margin-top:8px;display:flex;gap:8px;">
                        <button class="btn btn-sm" onclick="addPortfolioRow()" style="background:#607D8B;color:white;">+ 添加</button>
                        <button class="btn btn-primary btn-sm" onclick="checkPortfolio()">诊断持仓</button>
                    </div>
                    <div id="portfolio-result" style="margin-top:8px;display:none;"></div>
                </div>
            </div>
        </div>
    `;
}

async function scanOpportunities() {
    const minScore = document.getElementById("timing-min-score").value;
    const topn = document.getElementById("timing-topn").value;
    const status = document.getElementById("timing-status");

    status.textContent = "⏳ 扫描中...";
    const data = await api(`/aip/opportunities?min_score=${minScore}&top_n=${topn}`);
    status.textContent = data ? `✅ 发现 ${data.count} 个机会` : "❌ 失败";

    if (!data || !data.opportunities || !data.opportunities.length) {
        document.getElementById("timing-results").innerHTML =
            '<div class="empty">当前暂无符合条件的定投机会（市场可能整体偏贵）</div>';
        return;
    }

    let html = `<table class="data-table"><thead><tr>
        <th>时机评分</th><th>代码</th><th>PE分位</th><th>定投倍数</th><th>买入信号</th><th>趋势</th><th>建议</th>
    </tr></thead><tbody>`;

    data.opportunities.forEach(r => {
        const buyTags = (r.buy_signals || []).map(s => `<span class="badge badge-green" style="font-size:10px;">${s}</span>`).join(" ") || "—";
        html += `<tr>
            <td class="score-high">${r.timing_score?.toFixed(1) || '-'}</td>
            <td><a href="#" onclick="showFundDetail('${r.code}')" style="color:#2196F3;font-weight:500;">${r.code}</a></td>
            <td>${r.nav_percentile_2y?.toFixed(1) || '-'}%</td>
            <td>${multiplierBadge(r.aip_multiplier)}</td>
            <td>${buyTags}</td>
            <td>${r.trend_up ? '<span class="badge badge-green">↑ 向上</span>' : '<span class="badge badge-orange">↓ 走弱</span>'}</td>
            <td style="font-size:12px;">${r.advice || ''}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    document.getElementById("timing-results").innerHTML = html;

    // 缓存扫描结果，切换页面后无需重新扫描
    _timingCache = { minScore: parseInt(minScore), topn: parseInt(topn), html };
}

async function diagnoseFund() {
    const code = document.getElementById("diag-code").value.trim();
    const cost = document.getElementById("diag-cost").value;
    const status = document.getElementById("diag-status");
    if (!code) { status.textContent = "请输入基金代码"; return; }

    status.textContent = "⏳ 分析中...";
    let url = `/aip/timing/${code}`;
    if (cost) url += `?cost_nav=${cost}`;
    const data = await api(url);
    status.textContent = data && !data.error ? "✅" : "❌";

    const resultDiv = document.getElementById("diagnosis-result");
    if (!data || data.error) {
        resultDiv.style.display = "block";
        resultDiv.innerHTML = `<div class="error">${data?.error || '诊断失败'}</div>`;
        return;
    }

    resultDiv.style.display = "block";
    const buySigs = data.buy_signals || [];
    const sellSigs = data.sell_signals || [];
    const stopSigs = data.stop_profit_signals || [];

    resultDiv.innerHTML = `
        <div style="margin-top:8px;">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                <span style="font-size:22px;font-weight:bold;color:#4CAF50;">${data.timing_score}分</span>
                <span>PE分位 <b>${data.nav_percentile_2y}%</b></span>
                <span>净值 <b>${data.current_nav}</b></span>
                ${multiplierBadge(data.aip_multiplier)}
            </div>
            <div style="margin-bottom:6px;font-weight:bold;font-size:14px;">${data.advice || ''}</div>

            ${buySigs.length ? `<div style="margin-bottom:4px;"><b>买入信号：</b></div>
            <div style="margin-bottom:8px;">${buySigs.map(s => signalBadge(s.icon + ' ' + s.name + '：' + s.description)).join('<br>')}</div>` : ''}

            ${sellSigs.length ? `<div style="margin-bottom:4px;"><b>卖出信号：</b></div>
            <div style="margin-bottom:8px;">${sellSigs.map(s => signalBadge(s.icon + ' ' + s.name + '：' + s.description)).join('<br>')}</div>` : ''}

            ${stopSigs.length ? `<div style="margin-bottom:4px;"><b>止盈建议：</b></div>
            <div>${stopSigs.map(s => signalBadge(s.icon + ' ' + s.name + '：' + s.action)).join('<br>')}</div>` : ''}

            <div style="margin-top:8px;font-size:11px;color:#888;">
                指标 | MA60斜率 ${data.indicators?.ma60_slope}% | MA120斜率 ${data.indicators?.ma120_slope}%
                | RSI ${data.indicators?.rsi14} | 波动率 ${data.indicators?.volatility}%
            </div>
        </div>
    `;
}

function addPortfolioRow() {
    const div = document.createElement("div");
    div.className = "portfolio-row";
    div.innerHTML = `
        <input type="text" class="pf-code" placeholder="基金代码" maxlength="6" style="width:100px;">
        <input type="number" class="pf-cost" placeholder="成本净值" step="0.0001" style="width:100px;">
        <input type="number" class="pf-shares" placeholder="份额" step="1" style="width:80px;">
        <button class="btn btn-sm" onclick="this.parentElement.remove()" style="background:#f44336;color:white;">×</button>
    `;
    document.getElementById("portfolio-entries").appendChild(div);
}

async function checkPortfolio() {
    const rows = document.querySelectorAll(".portfolio-row");
    const holdings = [];
    rows.forEach(row => {
        const code = row.querySelector(".pf-code").value.trim();
        const cost = parseFloat(row.querySelector(".pf-cost").value);
        const shares = parseFloat(row.querySelector(".pf-shares").value);
        if (code && cost > 0 && shares > 0) {
            holdings.push({ code, cost_nav: cost, shares });
        }
    });

    const resultDiv = document.getElementById("portfolio-result");
    if (!holdings.length) {
        resultDiv.style.display = "block";
        resultDiv.innerHTML = '<div class="error">请至少输入一只基金的完整信息</div>';
        return;
    }

    resultDiv.style.display = "block";
    resultDiv.innerHTML = '<div class="loading">诊断中...</div>';

    const data = await api("/aip/portfolio/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(holdings),
    });

    if (!data) {
        resultDiv.innerHTML = '<div class="error">诊断失败</div>';
        return;
    }

    const s = data.summary;
    let html = `
        <div style="margin-top:8px;padding:8px;background:#f5f5f5;border-radius:6px;margin-bottom:8px;">
            <b>组合汇总：</b> 成本 ¥${s.total_cost?.toLocaleString()} |
            市值 <span style="color:${s.total_profit>=0?'#4CAF50':'#f44336'}">¥${s.total_value?.toLocaleString()}</span> |
            盈亏 <span style="color:${s.total_profit>=0?'#4CAF50':'#f44336'};font-weight:bold;">${formatPct(s.total_profit_pct)}</span>
        </div>
        <table class="data-table"><thead><tr><th>代码</th><th>盈亏%</th><th>时机</th><th>操作</th><th>信号</th></tr></thead><tbody>
    `;

    data.holdings.forEach(h => {
        const profitColor = h.profit >= 0 ? '#4CAF50' : '#f44336';
        const actionColor = h.action === '加仓' ? '#4CAF50' : h.action === '止盈' ? '#9C27B0' : h.action === '减仓' || h.action === '清仓' ? '#f44336' : '#333';
        html += `<tr>
            <td><b>${h.code}</b></td>
            <td style="color:${profitColor};font-weight:bold;">${formatPct(h.profit_pct)}</td>
            <td>${h.timing_score?.toFixed(0) || '-'}分</td>
            <td style="color:${actionColor};font-weight:bold;">${h.action}</td>
            <td style="font-size:11px;">${h.action_detail || ''}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    resultDiv.innerHTML = html;
}

// 暴露到全局
window.scanOpportunities = scanOpportunities;
window.diagnoseFund = diagnoseFund;
window.addPortfolioRow = addPortfolioRow;
window.checkPortfolio = checkPortfolio;
window.showFundDetail = showFundDetail;

// ================================================================
//  📋 基金筛选页面
// ================================================================
function renderScreening() {
    const main = document.getElementById("page-content");
    const cache = _screeningCache;
    const mode = cache?.mode || "buy";
    const type = cache?.type || "";
    const topn = cache?.topn || 20;
    const cachedHtml = cache?.html || "";

    main.innerHTML = `
        <div class="filter-bar">
            <label>模式：</label>
            <select id="filter-mode">
                <option value="buy" ${mode==="buy"?"selected":""}>一笔买入</option>
                <option value="aip" ${mode==="aip"?"selected":""}>定投筛选</option>
            </select>
            <label>类型：</label>
            <select id="filter-type">
                <option value="" ${type===""?"selected":""}>全部指数型</option>
                <option value="指数型-股票" ${type==="指数型-股票"?"selected":""}>指数型-股票</option>
                <option value="指数型" ${type==="指数型"?"selected":""}>指数型-其他</option>
            </select>
            <label>Top-N：</label>
            <input type="number" id="filter-topn" value="${topn}" min="5" max="100" style="width:70px;">
            <button class="btn btn-primary" onclick="doScreening()">🔍 开始筛选</button>
            ${cachedHtml ? '<span style="font-size:12px;color:#4CAF50;">（已缓存，无需重新筛选）</span>' : ''}
            <span id="filter-status" style="margin-left:8px;font-size:12px;color:#888;"></span>
        </div>
        <div id="screening-results">
            ${cachedHtml || '<div class="empty">点击"开始筛选"获取指数基金排名</div>'}
        </div>
    `;
}

async function doScreening() {
    const mode = document.getElementById("filter-mode").value;
    const type = document.getElementById("filter-type").value;
    const topn = document.getElementById("filter-topn").value;
    const status = document.getElementById("filter-status");

    status.textContent = "⏳ 正在计算评分...";
    document.getElementById("screening-results").innerHTML =
        '<div class="loading">正在计算指数基金评分中...</div>';

    let url = `/funds/top?mode=${mode}&top_n=${topn}&refresh=true`;
    if (type) url += `&fund_type=${encodeURIComponent(type)}`;

    const data = await api(url);
    status.textContent = data ? `✅ 完成，共 ${data.count} 只` : "❌ 请求失败";

    if (!data || !data.results || !data.results.length) {
        document.getElementById("screening-results").innerHTML =
            '<div class="empty">暂无数据。请先运行 <code>python scheduler.py</code> 初始化数据</div>';
        return;
    }

    let headers, renderRow;
    if (mode === "aip") {
        headers = ["排名", "代码", "名称", "总分", "估值", "趋势", "波动", "风控", "跟踪", "定投评级", "净值分位"];
        renderRow = (r, i) => `
            <tr>
                <td><span class="${i < 3 ? 'rank-1' : ''}">${i + 1}</span></td>
                <td><a href="#" onclick="showFundDetail('${r.code}')" style="color:#2196F3;font-weight:500;">${r.code}</a></td>
                <td title="${r.name || ''}">${(r.name || '-').substring(0, 14)}</td>
                <td class="score-high">${r.total_score?.toFixed(1) || '-'}</td>
                <td>${r.valuation_score?.toFixed(1) || '-'}</td>
                <td>${r.trend_score?.toFixed(1) || '-'}</td>
                <td>${r.volatility_score?.toFixed(1) || '-'}</td>
                <td>${r.risk_score?.toFixed(1) || '-'}</td>
                <td>${r.tracking_score?.toFixed(1) || '-'}</td>
                <td>${signalBadge(r.aip_rating)}</td>
                <td>${r.nav_percentile_2y?.toFixed(1) || '-'}%</td>
            </tr>`;
    } else {
        headers = ["排名", "代码", "名称", "总分", "收益", "估值", "风控", "技术", "跟踪", "位置风险", "净值分位"];
        renderRow = (r, i) => `
            <tr>
                <td><span class="${i < 3 ? 'rank-1' : ''}">${i + 1}</span></td>
                <td><a href="#" onclick="showFundDetail('${r.code}')" style="color:#2196F3;font-weight:500;">${r.code}</a></td>
                <td title="${r.name || ''}">${(r.name || '-').substring(0, 14)}</td>
                <td class="score-high">${r.total_score?.toFixed(1) || '-'}</td>
                <td>${r.return_score?.toFixed(1) || '-'}</td>
                <td>${r.valuation_score?.toFixed(1) || '-'}</td>
                <td>${r.risk_score?.toFixed(1) || '-'}</td>
                <td>${r.technical_score?.toFixed(1) || '-'}</td>
                <td>${r.tracking_score?.toFixed(1) || '-'}</td>
                <td>${signalBadge(r.position_risk)}</td>
                <td>${r.nav_percentile_2y?.toFixed(1) || '-'}%</td>
            </tr>`;
    }

    let html = '<table class="data-table"><thead><tr>' +
        headers.map(h => `<th>${h}</th>`).join("") + '</tr></thead><tbody>';
    data.results.forEach((r, i) => { html += renderRow(r, i); });
    html += '</tbody></table>';
    document.getElementById("screening-results").innerHTML = html;

    // 缓存筛选结果，切换页面后无需重新请求
    _screeningCache = { mode, type, topn, html };
}

window.doScreening = doScreening;

// ================================================================
//  🔍 基金详情页
// ================================================================
function showFundDetail(code) {
    // 记住当前所在页面，用于返回
    const activeTab = document.querySelector(".tab.active");
    _lastPage = activeTab ? activeTab.dataset.page : null;

    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelector('[data-page="detail"]').classList.add("active");
    renderDetail(code);
}

async function renderDetail(code) {
    const main = document.getElementById("page-content");
    if (!code) {
        main.innerHTML = `
            <div class="filter-bar">
                <label>基金代码：</label>
                <input type="text" id="detail-code" placeholder="6位基金代码" maxlength="6" style="width:120px;">
                <button class="btn btn-primary" onclick="showFundDetail(document.getElementById('detail-code').value)">查询</button>
                <span style="font-size:12px;color:#888;">仅支持指数型基金</span>
            </div>
            <div class="empty">输入基金代码查看详情</div>
        `;
        return;
    }

    main.innerHTML = '<div class="loading">加载中...</div>';
    const data = await api(`/funds/${code}`);
    if (!data || !data.basic || !data.basic.code) {
        main.innerHTML = `
            <div class="filter-bar">
                <button class="btn btn-back" onclick="goBack()" style="background:#607D8B;color:white;">← 返回</button>
                <span style="color:#f44336;">基金不存在或暂无数据</span>
            </div>`;
        return;
    }

    const b = data.basic;
    const scores = data.scores?.[0] || {};
    const signal = data.signal || {};
    const feeTotal = ((b.fee_mgmt || 0) + (b.fee_custody || 0)).toFixed(2);

    // 生成返回按钮（仅当从其他页面跳转过来时显示）
    const backBtn = _lastPage
        ? `<button class="btn btn-back" onclick="goBack()" style="background:#607D8B;color:white;">← 返回${_lastPage==='screening'?'筛选':_lastPage==='timing'?'定投决策':''}</button>`
        : '';

    main.innerHTML = `
        <div class="filter-bar">
            ${backBtn}
            <span style="font-weight:bold;">${b.code} — ${b.name}</span>
            <span style="color:#888;">${b.fund_type || '-'} | ${b.company || '-'} | 规模 ${(b.scale||0).toFixed(1)}亿 | 费率 ${feeTotal}%</span>
        </div>
        <div class="metrics-row">
            <div class="metric-card"><div class="label">综合评分</div><div class="value value-green">${scores.total_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">同类排名</div><div class="value value-orange">#${scores.rank_in_type || '-'}</div></div>
            <div class="metric-card"><div class="label">收益分</div><div class="value">${scores.return_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">估值分</div><div class="value">${scores.valuation_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">风控分</div><div class="value">${scores.risk_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">基本面分</div><div class="value">${scores.fundamental_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">技术分</div><div class="value">${scores.technical_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">跟踪误差分</div><div class="value">${scores.tracking_score?.toFixed(1) || '-'}</div></div>
        </div>
        <div class="detail-grid">
            <div class="card"><h3>基本信息</h3>
                <table style="width:100%;font-size:13px;">
                    <tr><td style="color:#888;padding:4px 0;">基金经理</td><td>${b.manager_name || '-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">成立日期</td><td>${b.establish_date || '-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">管理费率</td><td>${(b.fee_mgmt||0).toFixed(2)}%</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">托管费率</td><td>${(b.fee_custody||0).toFixed(2)}%</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">跟踪标的</td><td>${b.benchmark || '-'}</td></tr>
                </table>
            </div>
            <div class="card"><h3>技术信号</h3>
                <table style="width:100%;font-size:13px;">
                    <tr><td style="color:#888;padding:4px 0;">MA5/MA20/MA60</td><td>${signal.ma5?.toFixed(4)||'-'} / ${signal.ma20?.toFixed(4)||'-'} / ${signal.ma60?.toFixed(4)||'-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">MACD DIF/DEA</td><td>${signal.macd_dif?.toFixed(4)||'-'} / ${signal.macd_dea?.toFixed(4)||'-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">RSI(14)</td><td style="color:${(signal.rsi14||50)>70?'#f44336':(signal.rsi14||50)<30?'#4CAF50':'#333'}">${signal.rsi14?.toFixed(1)||'-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">布林上/中/下</td><td>${signal.bb_upper?.toFixed(4)||'-'} / ${signal.bb_mid?.toFixed(4)||'-'} / ${signal.bb_lower?.toFixed(4)||'-'}</td></tr>
                </table>
            </div>
        </div>
        <div class="card" style="margin-bottom:16px;"><h3>净值走势</h3><div id="nav-chart" class="chart-container"></div></div>
    `;

    const navHistory = data.nav_history || [];
    if (navHistory.length > 0) {
        const chartDom = document.getElementById("nav-chart");
        if (chartDom) {
            const chart = echarts.init(chartDom);
            const dates = navHistory.map(r => r.date);
            const values = navHistory.map(r => r.adj_nav || r.unit_nav);
            chart.setOption({
                tooltip: {
                    trigger: "axis",
                    formatter: function(params) {
                        const p = params[0];
                        return `<b>${p.axisValue}</b><br/>复权净值：<b style="color:#4CAF50">${Number(p.value).toFixed(4)}</b>`;
                    }
                },
                xAxis: {
                    type: "category",
                    data: dates,
                    axisLabel: {
                        show: true,
                        rotate: 0,
                        fontSize: 10,
                        color: "#999",
                        formatter: function(v) { return v.substring(0, 7); },  // YYYY-MM
                        interval: Math.max(1, Math.floor(dates.length / 12)),   // 自适应间隔
                    },
                    axisLine: { lineStyle: { color: "#ddd" } },
                },
                yAxis: { type: "value", name: "复权净值", scale: true, nameTextStyle: { fontSize: 11 } },
                dataZoom: [
                    {
                        type: "slider",
                        start: 0,
                        end: 100,
                        height: 22,
                        bottom: 6,
                        borderColor: "#ddd",
                        fillerColor: "rgba(76,175,80,0.15)",
                        handleStyle: { color: "#4CAF50" },
                        textStyle: { fontSize: 10 },
                    },
                    {
                        type: "inside",
                        start: 0,
                        end: 100,
                        zoomOnMouseWheel: true,
                        moveOnMouseMove: true,
                    }
                ],
                series: [{
                    name: b.name || code, type: "line",
                    data: values,
                    smooth: true, showSymbol: false,
                    lineStyle: { color: "#4CAF50", width: 1.5 },
                    areaStyle: { color: "rgba(76,175,80,0.1)" },
                }],
                grid: { left: 65, right: 20, top: 30, bottom: 50 },
            });
            window.addEventListener("resize", () => chart.resize());
        }
    }
}

// 返回上一页（从详情页返回筛选/定投决策页，保留缓存）
function goBack() {
    if (!_lastPage) return;
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    const targetTab = document.querySelector(`[data-page="${_lastPage}"]`);
    if (targetTab) {
        targetTab.classList.add("active");
        // 触发对应页面渲染（会从缓存恢复）
        if (_lastPage === "timing") renderTiming();
        else if (_lastPage === "screening") renderScreening();
        else if (_lastPage === "backtest") renderBacktest();
        else if (_lastPage === "config") renderConfig();
    }
    _lastPage = null;
}
window.goBack = goBack;

// ================================================================
//  📈 回测页面
// ================================================================
async function renderBacktest() {
    const main = document.getElementById("page-content");
    main.innerHTML = `
        <div class="filter-bar">
            <label>模式：</label><select id="bt-mode"><option value="buy">一笔买入</option><option value="aip">定投</option></select>
            <label>起始：</label><input type="date" id="bt-start" value="2022-01-01">
            <label>结束：</label><input type="date" id="bt-end" value="2025-12-31">
            <label id="lbl-rebalance">调仓周期(月)：</label><input type="number" id="bt-rebalance" value="3" min="1" max="12" style="width:60px;">
            <label>Top-N：</label><input type="number" id="bt-topn" value="10" min="1" max="50" style="width:60px;">
            <button class="btn btn-primary" onclick="doBacktest()">▶ 运行回测</button>
            <span id="bt-status" style="font-size:12px;color:#888;"></span>
        </div>
        <div id="backtest-results"><div class="empty">设置参数后点击"运行回测"</div></div>
    `;
    document.getElementById("bt-mode").addEventListener("change", function() {
        const isAip = this.value === "aip";
        document.getElementById("lbl-rebalance").style.display = isAip ? "none" : "";
        document.getElementById("bt-rebalance").style.display = isAip ? "none" : "";
    });
}

async function doBacktest() {
    const mode = document.getElementById("bt-mode").value;
    const start = document.getElementById("bt-start").value;
    const end = document.getElementById("bt-end").value;
    const reb = document.getElementById("bt-rebalance").value;
    const topn = document.getElementById("bt-topn").value;
    const status = document.getElementById("bt-status");
    status.textContent = "⏳ 回测运行中...";

    let url;
    if (mode === "aip") {
        url = `/backtest/aip?start_date=${start}&end_date=${end}&top_n=${topn}`;
    } else {
        url = `/backtest?mode=${mode}&start_date=${start}&end_date=${end}&rebalance_months=${reb}&top_n=${topn}`;
    }
    const data = await api(url);
    status.textContent = data && !data.error ? "✅ 完成" : "❌ 失败";
    if (!data || data.error) {
        document.getElementById("backtest-results").innerHTML = `<div class="error">${data?.error || '回测失败'}</div>`;
        return;
    }
    const m = data.metrics;
    let extra = "";
    if (mode === "aip") {
        extra = `
            <div class="metric-card"><div class="label">总投入</div><div class="value">¥${(data.total_invested||0).toLocaleString()}</div></div>
            <div class="metric-card"><div class="label">最终市值</div><div class="value value-green">¥${(data.final_value||0).toLocaleString()}</div></div>
            <div class="metric-card"><div class="label">IRR</div><div class="value value-green">${formatPct(data.irr)}</div></div>`;
    }
    document.getElementById("backtest-results").innerHTML = `
        <div class="metrics-row">
            <div class="metric-card"><div class="label">累计收益</div><div class="value ${m.total_return>=0?'value-green':'value-red'}">${formatPct(m.total_return)}</div></div>
            <div class="metric-card"><div class="label">年化收益</div><div class="value ${m.annual_return>=0?'value-green':'value-red'}">${formatPct(m.annual_return)}</div></div>
            <div class="metric-card"><div class="label">最大回撤</div><div class="value value-red">${formatPct(m.max_drawdown)}</div></div>
            <div class="metric-card"><div class="label">夏普比率</div><div class="value ${m.sharpe>=1?'value-green':(m.sharpe>=0.5?'value-orange':'value-red')}">${m.sharpe}</div></div>
            <div class="metric-card"><div class="label">胜率</div><div class="value">${m.win_rate}%</div></div>
            <div class="metric-card"><div class="label">超额收益</div><div class="value ${m.alpha>=0?'value-green':'value-red'}">${formatPct(m.alpha)}</div></div>
            <div class="metric-card"><div class="label">信息比率</div><div class="value">${m.info_ratio}</div></div>
            <div class="metric-card"><div class="label">基准收益</div><div class="value">${formatPct(m.benchmark_return)}</div></div>
            ${extra}
        </div>
        <div class="card"><h3>收益曲线（策略 vs 基准）</h3><div id="bt-chart" class="chart-container"></div></div>`;

    const pCurve = data.portfolio_curve || [];
    const bCurve = data.benchmark_curve || [];
    if (pCurve.length > 0) {
        const chartDom = document.getElementById("bt-chart");
        if (chartDom) {
            const chart = echarts.init(chartDom);
            const dates = pCurve.map(p => p.date);
            chart.setOption({
                tooltip: { trigger: "axis" },
                legend: { data: ["策略", "基准"] },
                xAxis: {
                    type: "category",
                    data: dates,
                    axisLabel: {
                        fontSize: 10, color: "#999",
                        formatter: function(v) { return v.substring(0, 7); },
                        interval: Math.max(1, Math.floor(dates.length / 12)),
                    },
                    axisLine: { lineStyle: { color: "#ddd" } },
                },
                yAxis: { type: "value", name: "净值" },
                dataZoom: [
                    {
                        type: "slider", start: 0, end: 100, height: 22, bottom: 6,
                        borderColor: "#ddd", fillerColor: "rgba(76,175,80,0.15)",
                        handleStyle: { color: "#4CAF50" }, textStyle: { fontSize: 10 },
                    },
                    { type: "inside", start: 0, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true },
                ],
                series: [
                    { name: "策略", type: "line", data: pCurve.map(p => p.value), smooth: true, showSymbol: false, lineStyle: { color: "#4CAF50", width: 2 } },
                    { name: "基准", type: "line", data: bCurve.map(b => b.value), smooth: true, showSymbol: false, lineStyle: { color: "#ddd", width: 1.5 } },
                ],
                grid: { left: 60, right: 20, top: 40, bottom: 50 },
            });
            window.addEventListener("resize", () => chart.resize());
        }
    }
}
window.doBacktest = doBacktest;

// ================================================================
//  ⚙️ 配置页
// ================================================================
async function renderConfig() {
    const main = document.getElementById("page-content");
    const data = await api("/config/weights");
    const buyDW = data?.buy?.dim_weights || {};
    const aipDW = data?.aip?.dim_weights || {};

    const dimLabels = {
        "return_": "收益", "valuation": "估值", "risk": "风控",
        "fundamental": "基本面", "technical": "技术", "tracking": "跟踪误差",
        "trend": "长期趋势", "volatility": "波动率",
    };

    main.innerHTML = `
        <div class="config-section">
            <h3>📊 系统概览</h3>
            <table style="font-size:13px;">
                <tr><td style="color:#888;padding:4px 8px;">基金范围</td><td>指数型基金</td></tr>
                <tr><td style="color:#888;padding:4px 8px;">无风险利率</td><td>${data?.risk_free_rate || 1.7}%</td></tr>
                <tr><td style="color:#888;padding:4px 8px;">定投决策</td><td>买入/卖出信号 + 定投倍数 + 止盈建议</td></tr>
                <tr><td style="color:#888;padding:4px 8px;">修改配置</td><td>编辑 <code>backend/config.py</code> 后重启</td></tr>
            </table>
        </div>
        <div class="config-section">
            <h3>📈 一笔买入 权重</h3>
            <div>${Object.entries(buyDW).map(([k, v]) => `<div class="weight-slider"><span class="dim-label">${dimLabels[k]||k}</span><input type="range" min="0" max="100" value="${(v*100).toFixed(0)}" disabled><span class="dim-value">${(v*100).toFixed(0)}%</span></div>`).join("")}</div>
        </div>
        <div class="config-section">
            <h3>💵 定投模式 权重</h3>
            <div>${Object.entries(aipDW).map(([k, v]) => `<div class="weight-slider"><span class="dim-label">${dimLabels[k]||k}</span><input type="range" min="0" max="100" value="${(v*100).toFixed(0)}" disabled><span class="dim-value">${(v*100).toFixed(0)}%</span></div>`).join("")}</div>
        </div>
    `;
}

// ========== 初始化：默认显示定投决策 ==========
renderTiming();
