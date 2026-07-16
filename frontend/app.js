const API = (function() {
    if (window.location.protocol === "file:") return "http://localhost:8000/api";
    return window.location.origin + "/api";
})();

function escHtml(s) {
    if (!s) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function escAttr(s) {
    if (!s) return "";
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function fmt(v) { if (v === null || v === undefined || isNaN(v) || v === "") return "-"; var p = Number(v).toFixed(2); return (v > 0 ? "+" : "") + p + "%"; }
function clr(v) { if (v === null || v === undefined || isNaN(v)) return ""; return v > 0 ? "up" : v < 0 ? "down" : ""; }
function sclr(s) { if (s >= 80) return "s-hi"; if (s >= 65) return "s-gd"; if (s >= 50) return "s-md"; return "s-lo"; }

function maLabel(n) {
    if (n >= 3) return '<span class="tag g">年季半</span>';
    if (n === 2) return '<span class="tag y">2条</span>';
    if (n === 1) return '<span class="tag o">1条</span>';
    return '<span class="tag r">0</span>';
}

function warnLabel(w) {
    if (!w) return "";
    if (w.includes("追高")) return '<span class="tag r">追高</span>';
    if (w.includes("低估")) return '<span class="tag g">低估</span>';
    return "";
}

async function load(force) {
    var el = document.getElementById("loading"), err = document.getElementById("error");
    var tbl = document.getElementById("table"), fr = document.getElementById("freshness");
    err.style.display = "none"; tbl.style.display = "none";
    var t0 = Date.now();
    el.style.display = "block"; el.textContent = "正在分析...";
    var timer = setInterval(function () {
        el.textContent = "正在分析 " + Math.round((Date.now() - t0) / 1000) + " 秒...(2000+只基金)";
    }, 1000);

    var controller = new AbortController();
    var timeoutId = setTimeout(function () { controller.abort(); }, 120000);

    try {
        var res = await fetch(API + "/top20" + (force ? "?refresh=true" : ""), { signal: controller.signal });
        clearInterval(timer);
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error("HTTP " + res.status);
        var data = await res.json();
        if (!data.results || !data.results.length) { err.textContent = "暂无符合条件的基金"; err.style.display = "block"; el.style.display = "none"; return; }
        render(data);
        tbl.style.display = ""; el.style.display = "none";
        fr.textContent = data.updated_at + " (" + Math.round((Date.now() - t0) / 1000) + "s)"; fr.className = "fresh";
    } catch (e) {
        clearInterval(timer);
        clearTimeout(timeoutId);
        if (e.name === "AbortError") {
            err.textContent = "加载超时，请重试";
        } else {
            err.textContent = "加载失败: " + e.message;
        }
        err.style.display = "block"; el.style.display = "none";
    }
}

// 跨引擎一致性：记录Top20推荐基金代码，用于持仓页冲突检测
var _top20Codes = [];

function render(data) {
    var h = "";
    _top20Codes = [];
    data.results.forEach(function (r, i) {
        _top20Codes.push(r.code);
        var n = i + 1, top = n <= 3 ? " top" : "";
        h += '<tr class="clickable" onclick="showDetail(\'' + escAttr(r.code) + '\', \'' + escAttr(r.name) + '\')">';
        h += '<td class="rnk' + n + top + '">' + n + '</td>';
        h += '<td class="code">' + escHtml(r.code) + '</td>';
        h += '<td class="name" title="' + escAttr(r.name) + '">' + escHtml(r.name) + '</td>';
        h += '<td class="' + sclr(r.score) + ' bold">' + r.score + '</td>';
        h += '<td class="' + clr(r.ret_5d) + '">' + fmt(r.ret_5d) + '</td>';
        h += '<td class="' + clr(r.ret_20d) + '">' + fmt(r.ret_20d) + '</td>';
        h += '<td class="' + clr(r.ret_1y) + '">' + fmt(r.ret_1y) + '</td>';
        h += '<td>' + r.nav_pct_2y + '%</td>';
        h += '<td class="' + clr(r.drawdown) + '">' + fmt(r.drawdown) + '</td>';
        h += '<td>' + maLabel(r.ma_below) + '</td>';
        h += '<td>' + r.rsi + '</td>';
        h += '<td>' + volLabel(r.volatility) + '</td>';
        h += '<td>' + bbLabel(r.bb_position) + '</td>';
        h += '<td>' + r.consecutive_down + '天</td>';
        h += '<td>' + warnLabel(r.warning) + '</td>';
        h += '</tr>';
    });
    document.getElementById("tbody").innerHTML = h;
}

function volLabel(v) {
    if (!v) return '<span class="tag">-</span>';
    if (v > 40) return '<span class="tag r">高(' + v + '%)</span>';
    if (v > 25) return '<span class="tag o">中(' + v + '%)</span>';
    return '<span class="tag g">低(' + v + '%)</span>';
}

function bbLabel(pos) {
    if (!pos) return '<span class="tag">-</span>';
    if (pos.indexOf("下轨") >= 0) return '<span class="tag g">' + pos + '</span>';
    if (pos.indexOf("中轨下方") >= 0) return '<span class="tag y">' + pos + '</span>';
    return '<span class="tag">' + pos + '</span>';
}

// ============================================================
// 详情弹窗
// ============================================================
var navChart = null, rsiChart = null, macdChart = null;
var detailData = null, currentRange = "all";

function filterByRange(data, range) {
    if (range === "all") return data;
    var days = { "3y": 756, "1y": 252, "6m": 126, "3m": 63, "1m": 21 };
    var cutoff = days[range] || 0;
    if (cutoff === 0 || data.length <= cutoff) return data;
    return data.slice(-cutoff);
}

function chartColors() {
    var style = getComputedStyle(document.body);
    return {
        nav: style.getPropertyValue("--c-up") || "#e15241",
        grid: style.getPropertyValue("--c-border") || "#e0e0e0",
        text: style.getPropertyValue("--c-text") || "#666",
        rsiLine: "#7b4bff",
        rsiHi: "rgba(225,82,65,0.15)",
        rsiLo: "rgba(0,179,110,0.15)",
        macdUp: "rgba(225,82,65,0.6)",
        macdDn: "rgba(0,179,110,0.6)",
        dif: "#e15241",
        dea: "#f5a623",
        ma20: "#f5a623",
        ma60: "#7b4bff",
        ma120: "#00b36e"
    };
}

async function showDetail(code, name) {
    document.getElementById("modal-title").textContent = name + " (" + code + ")";
    document.getElementById("modal-overlay").style.display = "flex";
    document.getElementById("detail-stats").innerHTML = '<div class="loading">加载中...</div>';

    try {
        var res = await fetch(API + "/fund/" + code);
        if (!res.ok) throw new Error("HTTP " + res.status);
        var d = await res.json();
        if (d.error) throw new Error(d.error);
        detailData = d;
        currentRange = "all";
        document.querySelectorAll(".rng-btn").forEach(function (b) { b.classList.toggle("active", b.dataset.range === "all"); });
        renderCharts(d, "all");
        renderStats(d);
        renderTechnicals(code);
    } catch (e) {
        document.getElementById("detail-stats").innerHTML = '<div class="error">加载失败: ' + escHtml(e.message) + '</div>';
    }
}

function renderCharts(d, range) {
    range = range || "all";
    var C = chartColors();
    var signals = filterByRange(d.signals, range);
    var navHistory = filterByRange(d.nav_history, range);

    // 净值图：用筛选后的净值历史
    var navDates = navHistory.map(function (n) { return n.date; });
    var navs = navHistory.map(function (n) { return n.nav; });

    // 信号对齐到净值日期
    var sigMap = {};
    signals.forEach(function (s) { sigMap[s.date] = s; });
    var ma20 = navDates.map(function (dt) { var s = sigMap[dt]; return s ? s.ma20 : null; });
    var ma60 = navDates.map(function (dt) { var s = sigMap[dt]; return s ? s.ma60 : null; });
    var ma120 = navDates.map(function (dt) { var s = sigMap[dt]; return s ? s.ma120 : null; });

    // 净值+均线
    if (navChart) navChart.destroy();
    navChart = new Chart(document.getElementById("chart-nav"), {
        type: "line",
        data: {
            labels: navDates,
            datasets: [
                { label: "净值", data: navs, borderColor: C.nav, borderWidth: 1.5, pointRadius: 0, tension: 0.1 },
                { label: "MA20", data: ma20, borderColor: C.ma20, borderWidth: 1, pointRadius: 0, borderDash: [4, 2] },
                { label: "MA60", data: ma60, borderColor: C.ma60, borderWidth: 1, pointRadius: 0, borderDash: [4, 2] },
                { label: "MA120", data: ma120, borderColor: C.ma120, borderWidth: 1, pointRadius: 0, borderDash: [4, 2] }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { position: "top", labels: { boxWidth: 20, padding: 10, font: { size: 11 } } } },
            scales: {
                x: { display: true, ticks: { maxTicksLimit: 12, font: { size: 10 } }, grid: { color: C.grid } },
                y: { grid: { color: C.grid }, ticks: { font: { size: 10 } } }
            }
        }
    });

    // RSI + MACD 用筛选后的信号日期
    var sigDates = signals.map(function (s) { return s.date; });
    var rsis = signals.map(function (s) { return s.rsi || null; });
    var difs = signals.map(function (s) { return s.macd_dif || null; });
    var deas = signals.map(function (s) { return s.macd_dea || null; });
    var hists = signals.map(function (s) { return s.macd_hist || null; });

    // RSI
    if (rsiChart) rsiChart.destroy();
    rsiChart = new Chart(document.getElementById("chart-rsi"), {
        type: "line",
        data: {
            labels: sigDates,
            datasets: [{
                label: "RSI(14)", data: rsis, borderColor: C.rsiLine, borderWidth: 1.5, pointRadius: 0,
                fill: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                annotation: false
            },
            scales: {
                x: { display: true, ticks: { maxTicksLimit: 8, font: { size: 10 } }, grid: { color: C.grid } },
                y: { min: 0, max: 100, grid: { color: C.grid }, ticks: { font: { size: 10 }, stepSize: 20 } }
            }
        },
        plugins: [{
            id: "rsiZones",
            beforeDraw: function (chart) {
                var ctx = chart.ctx, xAxis = chart.scales.x, yAxis = chart.scales.y;
                ctx.fillStyle = C.rsiHi;
                ctx.fillRect(xAxis.left, yAxis.getPixelForValue(70), xAxis.width, yAxis.getPixelForValue(100) - yAxis.getPixelForValue(70));
                ctx.fillStyle = C.rsiLo;
                ctx.fillRect(xAxis.left, yAxis.getPixelForValue(0), xAxis.width, yAxis.getPixelForValue(30) - yAxis.getPixelForValue(0));
            }
        }]
    });

    // MACD
    if (macdChart) macdChart.destroy();
    macdChart = new Chart(document.getElementById("chart-macd"), {
        type: "bar",
        data: {
            labels: sigDates,
            datasets: [
                { label: "MACD柱", data: hists, backgroundColor: hists.map(function (v) { return v >= 0 ? C.macdUp : C.macdDn; }), borderWidth: 0 },
                { label: "DIF", data: difs, borderColor: C.dif, borderWidth: 1, pointRadius: 0, type: "line" },
                { label: "DEA", data: deas, borderColor: C.dea, borderWidth: 1, pointRadius: 0, type: "line" }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { position: "top", labels: { boxWidth: 12, padding: 6, font: { size: 10 } } } },
            scales: {
                x: { display: true, ticks: { maxTicksLimit: 8, font: { size: 10 } }, grid: { color: C.grid } },
                y: { grid: { color: C.grid }, ticks: { font: { size: 10 } } }
            }
        }
    });
}

function renderStats(d) {
    var l = d.latest;
    var h = '<div class="stat-grid">';
    h += '<div class="stat"><span class="lbl">最新净值</span><span class="val">' + l.nav + '</span></div>';
    h += '<div class="stat"><span class="lbl">RSI(14)</span><span class="val">' + l.rsi + '</span></div>';
    h += '<div class="stat"><span class="lbl">MA20</span><span class="val">' + (l.ma20 ? l.ma20.toFixed(4) : "-") + '</span></div>';
    h += '<div class="stat"><span class="lbl">MA60</span><span class="val">' + (l.ma60 ? l.ma60.toFixed(4) : "-") + '</span></div>';
    h += '<div class="stat"><span class="lbl">MA120</span><span class="val">' + (l.ma120 ? l.ma120.toFixed(4) : "-") + '</span></div>';
    h += '<div class="stat"><span class="lbl">记录数</span><span class="val">' + d.record_count + '条</span></div>';
    h += '</div>';
    h += '<div class="ret-grid">';
    h += '<span>近5日: <b class="' + (d.returns.r5d >= 0 ? "up" : "down") + '">' + fmt(d.returns.r5d) + '</b></span>';
    h += '<span>近10日: <b class="' + (d.returns.r10d >= 0 ? "up" : "down") + '">' + fmt(d.returns.r10d) + '</b></span>';
    h += '<span>近20日: <b class="' + (d.returns.r20d >= 0 ? "up" : "down") + '">' + fmt(d.returns.r20d) + '</b></span>';
    h += '<span>近60日: <b class="' + (d.returns.r60d >= 0 ? "up" : "down") + '">' + fmt(d.returns.r60d) + '</b></span>';
    h += '<span>近1年: <b class="' + (d.returns.r1y >= 0 ? "up" : "down") + '">' + fmt(d.returns.r1y) + '</b></span>';
    h += '</div>';
    document.getElementById("detail-stats").innerHTML = h;
}

function renderTechnicals(code) {
    var el = document.getElementById("detail-technicals");
    el.innerHTML = '<div class="loading">加载技术指标...</div>';
    fetch(API + "/fund/" + code + "/technicals")
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.error) { el.innerHTML = ''; return; }
            var t = d.technicals;
            var h = '<h3>技术指标仪表盘</h3>';
            h += '<div class="tech-grid">';
            // RSI
            h += '<div class="tech-item"><span class="tlbl">RSI(14)</span><span class="tval ' + (t.rsi.zone === '超买' ? 'up' : t.rsi.zone === '超卖' ? 'down' : '') + '">' + t.rsi.value + '</span><span class="tz">' + t.rsi.zone + '</span></div>';
            // MACD
            h += '<div class="tech-item"><span class="tlbl">MACD</span><span class="tval">' + (t.macd.signal === '金叉' ? '<span class="up">金叉</span>' : '<span class="down">死叉</span>') + '</span><span class="tz">DIF:' + t.macd.dif + '</span></div>';
            // KDJ
            h += '<div class="tech-item"><span class="tlbl">KDJ</span><span class="tval">K:' + t.kdj.k + ' D:' + t.kdj.d + '</span><span class="tz">J:' + t.kdj.j + ' ' + t.kdj.signal + '</span></div>';
            // Bollinger
            var bbPos = '';
            var bbCls = '';
            if (t.bollinger.lower > 0) {
                bbPos = '上:' + t.bollinger.upper + ' 下:' + t.bollinger.lower;
            }
            h += '<div class="tech-item"><span class="tlbl">布林带</span><span class="tval">宽度:' + t.bollinger.width + '%</span><span class="tz">' + bbPos + '</span></div>';
            // MA
            h += '<div class="tech-item"><span class="tlbl">均线</span><span class="tval">MA20:' + t.ma.ma20 + '</span><span class="tz">MA60:' + t.ma.ma60 + ' MA120:' + t.ma.ma120 + '</span></div>';
            // ATR
            h += '<div class="tech-item"><span class="tlbl">ATR(14)</span><span class="tval">' + t.atr14 + '</span><span class="tz">日均波幅</span></div>';
            h += '</div>';
            el.innerHTML = h;
        }).catch(function () { el.innerHTML = ''; });
}

// 弹窗控制
document.getElementById("modal-close").onclick = closeDetail;
document.getElementById("modal-overlay").onclick = function (e) {
    if (e.target === this) closeDetail();
};

function closeDetail() {
    document.getElementById("modal-overlay").style.display = "none";
    if (navChart) { navChart.destroy(); navChart = null; }
    if (rsiChart) { rsiChart.destroy(); rsiChart = null; }
    if (macdChart) { macdChart.destroy(); macdChart = null; }
}

// 时间范围按钮
document.querySelectorAll(".rng-btn").forEach(function (btn) {
    btn.onclick = function () {
        document.querySelectorAll(".rng-btn").forEach(function (b) { b.classList.remove("active"); });
        this.classList.add("active");
        currentRange = this.dataset.range;
        if (detailData) renderCharts(detailData, currentRange);
    };
});

// 按钮
document.getElementById("refresh-btn").onclick = function () {
    this.textContent = "刷新中..."; this.disabled = true;
    load(true).finally(function () { this.textContent = "刷新数据"; this.disabled = false; }.bind(this));
};

// ============================================================
// 买卖建议（详情弹窗内）
// ============================================================
function renderAdvice(d) {
    var container = document.getElementById("detail-advice");
    container.innerHTML = '<div class="loading">加载买卖建议...</div>';

    var controller = new AbortController();
    var timeoutId = setTimeout(function () { controller.abort(); }, 30000);

    fetch(API + "/fund/" + d.code + "/advice", { signal: controller.signal })
        .then(function (r) { return r.json(); })
        .then(function (adv) {
            clearTimeout(timeoutId);
            if (adv.buy && adv.sell) {
                var h = '<h3>交易建议</h3>';

                // === 买入建议 ===
                var b = adv.buy;
                h += '<div class="advice-card">';
                h += '<div class="advice-title">买入建议：<span class="' + (b.dca_multiplier >= 1 ? 'up' : '') + '">' + escHtml(b.buy_urgency) + '</span></div>';
                h += '<div class="advice-body">';
                h += '<p>估值状态：<b>' + escHtml(b.valuation.label) + '</b>（历史分位 ' + b.valuation.pct + '%）</p>';
                h += '<p>定投倍数：<b>' + b.dca_multiplier + 'x</b> | 建议仓位：<b>' + escHtml(b.suggested_position) + '</b></p>';
                h += '<p>入场计划：' + escHtml(b.batch_plan) + '</p>';
                if (b.entry_points && b.entry_points.length > 0) {
                    h += '<p>参考价位：';
                    b.entry_points.forEach(function (ep) {
                        h += '<span class="tag y">' + escHtml(ep.level) + ': ' + ep.price + '</span> ';
                    });
                    h += '</p>';
                }
                if (b.grid_params) {
                    h += '<p>网格参数：间距<b>' + b.grid_params.spacing + '%</b> | ' + b.grid_params.suggested_grids + '格 | 区间[' + b.grid_params.lower + ' ~ ' + b.grid_params.upper + ']</p>';
                    if (b.grid_params.note) h += '<p class="grid-note">' + escHtml(b.grid_params.note) + '</p>';
                }
                if (b.risk_warnings && b.risk_warnings.length > 0) {
                    h += '<div class="risk">';
                    b.risk_warnings.forEach(function (w) { h += '<p>' + escHtml(w) + '</p>'; });
                    h += '</div>';
                }
                h += '</div></div>';

                // === 卖出信号 ===
                var s = adv.sell;
                var scls = s.sell_score >= 60 ? 'r' : s.sell_score >= 40 ? 'o' : s.sell_score >= 20 ? 'y' : 'g';
                h += '<div class="advice-card">';
                h += '<div class="advice-title">卖出信号：<span class="tag ' + scls + '">' + escHtml(s.summary) + '</span> <small>(紧迫度: ' + (s.sell_score || 0) + '/100)</small></div>';
                h += '<div class="advice-body">';
                if (s.profit_pct !== null && s.profit_pct !== undefined) {
                    h += '<p>持仓盈亏：<b class="' + (s.profit_pct >= 0 ? 'up' : 'down') + '">' + fmt(s.profit_pct) + '</b>';
                    if (s.holding_days) h += ' | 持有' + s.holding_days + '天';
                    h += '</p>';
                }
                h += '<p>净值：' + s.current_nav + ' | RSI：' + s.rsi + ' | 估值分位：' + s.nav_pct + '%</p>';

                // 信号列表
                if (s.signals && s.signals.length > 0) {
                    h += '<div class="signal-list">';
                    s.signals.forEach(function (sig) {
                        var lvl = sig.level >= 3 ? 'r' : sig.level >= 2 ? 'o' : sig.level >= 1 ? 'y' : '';
                        h += '<div class="signal-item ' + lvl + '"><b>' + escHtml(sig.type) + '</b>：' + escHtml(sig.msg) + '</div>';
                    });
                    h += '</div>';
                }

                // 操作计划（统一层级系统）
                if (s.action_plan) {
                    h += '<div class="action-plan">';
                    var lvlCls = s.action_plan.level === '清仓' ? 'r' : s.action_plan.level === '减仓' ? 'o' : 'y';
                    h += '<div class="ap-title"><span class="tag ' + lvlCls + '">' + escHtml(s.action_plan.level || '') + '</span> 综合评分: ' + (s.sell_score || 0) + '/100';
                    if (s.action_plan.suggested_sell_pct > 0) {
                        h += ' — 建议卖出 ' + s.action_plan.suggested_sell_pct + '%';
                    }
                    h += '</div>';
                    if (s.action_plan.action) {
                        h += '<div class="ap-item"><b>建议操作：</b>' + escHtml(s.action_plan.action) + '</div>';
                    }
                    if (s.action_plan.triggered_reasons && s.action_plan.triggered_reasons.length > 0) {
                        h += '<div class="ap-title">触发原因：</div>';
                        s.action_plan.triggered_reasons.forEach(function (r) {
                            h += '<div class="ap-item"><span class="tag o">触发</span> ' + escHtml(r) + '</div>';
                        });
                    }
                    if (s.action_plan.monitor_items && s.action_plan.monitor_items.length > 0) {
                        h += '<div class="ap-title">持续监控：</div>';
                        s.action_plan.monitor_items.forEach(function (m) {
                            h += '<div class="ap-item"><span class="tag y">监控</span> ' + escHtml(m) + '</div>';
                        });
                    }
                    h += '<div class="ap-next">下次复查：' + (s.action_plan.next_review_date || '-') + '</div>';
                    h += '</div>';
                }
                h += '</div></div>';
                container.innerHTML = h;
            } else {
                container.innerHTML = '<div class="error">建议加载失败</div>';
            }
        }).catch(function (e) {
            clearTimeout(timeoutId);
            if (e.name === "AbortError") {
                container.innerHTML = '<div class="error">加载建议超时</div>';
            } else {
                container.innerHTML = '<div class="error">建议加载失败: ' + escHtml(e.message) + '</div>';
            }
        });
}

// 修改 showDetail 同时加载建议
var _origShowDetail = showDetail;
showDetail = function (code, name) {
    _origShowDetail(code, name);
    var d = { code: code, name: name };
    renderAdvice(d);
};

// ============================================================
// 持仓管理
// ============================================================

function loadPortfolio() {
    fetch(API + "/portfolio/analysis")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            renderPortfolioSummary(data);
            renderPortfolioList(data);
            // 更新已持有基金列表
            _heldCodes = [];
            if (data.details) data.details.forEach(function (h) { _heldCodes.push(h.code); });
        }).catch(function (e) {
            console.error("加载持仓失败:", e);
        });
}

function renderPortfolioSummary(data) {
    var el = document.getElementById("portfolio-summary");
    if (data.status === "empty") {
        el.innerHTML = '<div class="empty-hint">暂无持仓，点击「＋ 添加持仓」开始管理</div>';
        document.getElementById("portfolio-risk").style.display = "none";
        return;
    }
    var h = '<div class="summary-cards">';
    h += '<div class="scard"><span class="slbl">总投入</span><span class="sval">¥' + data.total_invested.toLocaleString() + '</span></div>';
    h += '<div class="scard"><span class="slbl">当前市值</span><span class="sval">¥' + data.total_value.toLocaleString() + '</span></div>';
    var pcls = data.total_profit >= 0 ? "up" : "down";
    h += '<div class="scard"><span class="slbl">总盈亏</span><span class="sval ' + pcls + '">' + fmt(data.total_profit_pct) + ' (¥' + Math.round(data.total_profit).toLocaleString() + ')</span></div>';
    h += '<div class="scard"><span class="slbl">持仓数</span><span class="sval">' + data.holdings_count + '只</span></div>';

    // 风险指标
    if (data.risk_metrics && data.risk_metrics.portfolio_volatility) {
        h += '<div class="scard"><span class="slbl">组合波动率</span><span class="sval">' + data.risk_metrics.portfolio_volatility + '%</span></div>';
    }
    h += '</div>';

    // 赛道分布
    if (data.sector_allocation && Object.keys(data.sector_allocation).length > 0) {
        h += '<div class="sector-bar">';
        Object.keys(data.sector_allocation).forEach(function (k) {
            var v = data.sector_allocation[k];
            var cls = v.pct > 30 ? 'sbar-item warn' : 'sbar-item';
            h += '<span class="' + cls + '" title="' + k + ' ' + v.pct + '%">' + k + ' <b>' + v.pct + '%</b></span>';
        });
        h += '</div>';
    }

    // 警告
    if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach(function (w) {
            h += '<div class="warn-msg">⚠ ' + escHtml(w) + '</div>';
        });
    }

    // 相关性警告
    if (data.correlation_warnings && data.correlation_warnings.length > 0) {
        data.correlation_warnings.forEach(function (cw) {
            h += '<div class="warn-msg">🔗 ' + escHtml(cw.msg) + '</div>';
        });
    }

    // 再平衡建议
    if (data.rebalance_advice) {
        h += '<div class="rebalance-msg">💡 ' + escHtml(data.rebalance_advice) + '</div>';
    }

    // 再平衡操作清单
    if (data.rebalance_actions && data.rebalance_actions.length > 0) {
        h += '<div class="rebalance-actions">';
        data.rebalance_actions.forEach(function (ra) {
            h += '<div class="ra-item"><span class="tag ' + (ra.priority === 'high' ? 'r' : 'y') + '">' + escHtml(ra.priority) + '</span> ' + escHtml(ra.action) + '：' + escHtml(ra.detail) + '</div>';
        });
        h += '</div>';
    }

    // 卖出优先
    if (data.sell_priority && data.sell_priority.length > 0) {
        h += '<div class="sell-priority">🔴 优先关注卖出：';
        data.sell_priority.forEach(function (sp) {
            h += '<span class="tag r">' + escHtml(sp.name) + '(' + fmt(sp.profit_pct) + ')</span> ';
        });
        h += '</div>';
    }

    // 现金管理建议
    if (data.cash_advice) {
        h += '<div class="cash-advice">💰 仓位建议：权益<b>' + data.cash_advice.suggested_equity_pct + '%</b> / 现金<b>' + data.cash_advice.suggested_cash_pct + '%</b>（基于平均估值分位' + data.cash_advice.avg_valuation_pct + '%）</div>';
    }

    el.innerHTML = h;
}

function renderPortfolioList(data) {
    var el = document.getElementById("portfolio-list");
    if (data.status === "empty" || !data.details) {
        el.innerHTML = "";
        return;
    }
    var h = '<table class="pf-table"><thead><tr>';
    h += '<th>代码</th><th>名称</th><th>买入日</th><th>成本</th><th>现价</th><th>盈亏</th><th>赛道</th><th>卖出建议</th><th>操作</th>';
    h += '</tr></thead><tbody>';
    data.details.forEach(function (d) {
        h += '<tr>';
        h += '<td class="code clickable" onclick="showDetail(\'' + escAttr(d.code) + '\', \'' + escAttr(d.name) + '\')" title="点击查看详情">' + escHtml(d.code) + '</td>';
        h += '<td class="name clickable" onclick="showDetail(\'' + escAttr(d.code) + '\', \'' + escAttr(d.name) + '\')" title="点击查看详情">' + escHtml(d.name) + '</td>';
        h += '<td>' + d.buy_date + '</td>';
        h += '<td>' + d.buy_nav + '</td>';
        h += '<td>' + d.current_nav + '</td>';
        h += '<td class="' + (d.profit_pct >= 0 ? 'up' : 'down') + '">' + fmt(d.profit_pct) + '</td>';
        h += '<td><span class="tag">' + escHtml(d.sector) + '</span></td>';
        var sa = d.sell_score || 0;
        var scls = sa >= 70 ? 'r' : sa >= 45 ? 'o' : sa >= 20 ? 'y' : 'g';
        var suggestedPct = d.suggested_sell_pct || 0;
        var pctDisplay = suggestedPct > 0 ? '<span class="suggest-pct">建议卖' + suggestedPct + '%</span>' : '';
        h += '<td title="卖出紧迫度: ' + sa + '/100"><span class="tag ' + scls + '">' + escHtml(d.sell_summary) + '</span> ' + pctDisplay;
        // 跨引擎一致性检测：该基金是否同时出现在Top20推荐中?
        if (_top20Codes.indexOf(d.code) >= 0 && sa > 0) {
            h += ' <span class="tag r" title="该基金同时出现在买入推荐和卖出信号中，请结合估值+趋势判断">⚠买卖冲突</span>';
        }
        h += '</td>';
        var btnCls = sa >= 70 ? 'btn-sell-urgent' : sa >= 45 ? 'btn-sell-warn' : 'btn-sell-sm';
        h += '<td><button class="' + btnCls + '" onclick="sellHolding(' + d.id + ',' + d.current_nav + ',\'' + escAttr(d.name) + '\',' + suggestedPct + ',' + sa + ')">卖出</button> ';
        h += '<button class="btn-ghost-sm" onclick="deleteHolding(' + d.id + ')">删除</button></td>';
        h += '</tr>';
    });
    h += '</tbody></table>';
    el.innerHTML = h;
}

function deleteHolding(id) {
    if (!confirm("确认删除这笔持仓记录？")) return;
    fetch(API + "/portfolio/" + id, { method: "DELETE" })
        .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(function (d) {
            if (d.error) { alert(d.error); return; }
            loadPortfolio(); loadHistory();
        })
        .catch(function (e) {
            alert("删除失败: " + e.message);
        });
}

function sellHolding(id, currentNav, name, suggestedPct, sellScore) {
    // 单步确认弹窗：一次显示全部信息并确认
    var pct = suggestedPct > 0 ? suggestedPct : (sellScore >= 70 ? 100 : sellScore >= 45 ? 50 : 30);
    var msgs = [];
    if (sellScore >= 70) msgs.push('紧迫度 ' + sellScore + '/100 - 强烈建议清仓');
    else if (sellScore >= 45) msgs.push('紧迫度 ' + sellScore + '/100 - 建议减仓');
    else if (sellScore >= 20) msgs.push('紧迫度 ' + sellScore + '/100 - 关注（暂不建议操作）');
    else msgs.push('卖出紧迫度: ' + (sellScore || 0) + '/100 - 继续持有中');

    var confirmMsg = '卖出「' + name + '」\n\n' +
        (msgs.length ? msgs.join('\n') + '\n\n' : '') +
        '卖出比例% (默认净值: ' + currentNav + ')\n' +
        '如需自定义净值，输入格式: 50@1.2345';
    var input = prompt(confirmMsg, pct);
    if (input === null || input === '') return;

    // 解析输入：支持 "50" 或 "50@1.2345" 格式
    var sellPct, sellNavNum;
    if (input.indexOf('@') >= 0) {
        var parts = input.split('@');
        sellPct = parseFloat(parts[0]);
        sellNavNum = parseFloat(parts[1]);
    } else {
        sellPct = parseFloat(input);
        sellNavNum = currentNav;
    }

    if (isNaN(sellPct) || sellPct <= 0 || sellPct > 100) {
        alert('请输入有效的卖出比例 (1-100)'); return;
    }
    if (isNaN(sellNavNum) || sellNavNum <= 0) {
        alert('请输入有效的卖出净值'); return;
    }

    fetch(API + '/portfolio/' + id + '/sell', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sell_nav: sellNavNum, sell_pct: sellPct })
    })
        .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(function (data) {
            if (data.error) { alert(data.error); return; }
            var resultMsg = sellPct >= 100 ? '已全部卖出 ' + data.name : '已卖出 ' + data.name + ' (' + data.sell_pct + '%)';
            alert(resultMsg + '\n卖出净值: ' + data.sell_nav +
                '\n盈亏: ' + (data.profit >= 0 ? '+' : '') + data.profit + '元 (' +
                (data.profit_pct >= 0 ? '+' : '') + data.profit_pct + '%)');
            loadPortfolio(); loadHistory();
        })
        .catch(function (e) {
            alert("卖出失败: " + e.message);
        });
}

function loadHistory() {
    fetch(API + "/portfolio/history")
        .then(function (r) { return r.json(); })
        .then(function (data) { renderHistory(data); })
        .catch(function (e) { console.error("加载历史失败:", e); });
}

function renderHistory(data) {
    var el = document.getElementById("portfolio-history");
    var listEl = document.getElementById("history-list");
    if (data.count === 0 || !data.history) {
        el.style.display = "none";
        return;
    }
    el.style.display = "block";
    var h = '<table class="pf-table"><thead><tr>';
    h += '<th>代码</th><th>名称</th><th>买入日</th><th>买入价</th><th>卖出日</th><th>卖出价</th><th>份额</th><th>盈亏</th><th>收益率</th><th>操作</th>';
    h += '</tr></thead><tbody>';
    data.history.forEach(function (d) {
        h += '<tr>';
        h += '<td class="code clickable" onclick="showDetail(\'' + escAttr(d.code) + '\', \'' + escAttr(d.name) + '\')" title="点击查看详情">' + escHtml(d.code) + '</td>';
        h += '<td class="name clickable" onclick="showDetail(\'' + escAttr(d.code) + '\', \'' + escAttr(d.name) + '\')" title="点击查看详情">' + escHtml(d.name) + '</td>';
        h += '<td>' + d.buy_date + '</td>';
        h += '<td>' + d.buy_nav + '</td>';
        h += '<td>' + d.sell_date + '</td>';
        h += '<td>' + d.sell_nav + '</td>';
        h += '<td>' + d.shares + '</td>';
        h += '<td class="' + (d.profit >= 0 ? 'up' : 'down') + '">' + (d.profit >= 0 ? '+' : '') + d.profit + '</td>';
        h += '<td class="' + (d.profit_pct >= 0 ? 'up' : 'down') + '">' + (d.profit_pct >= 0 ? '+' : '') + d.profit_pct + '%</td>';
        h += '<td><button class="btn-ghost-sm" onclick="deleteHolding(' + d.id + ')">删除</button></td>';
        h += '</tr>';
    });
    h += '</tbody></table>';
    listEl.innerHTML = h;
}

// 添加持仓按钮
document.getElementById("add-holding-btn").onclick = function () {
    document.getElementById("add-holding-form").style.display = "block";
    this.style.display = "none";
};

document.getElementById("hf-cancel").onclick = function () {
    document.getElementById("add-holding-form").style.display = "none";
    document.getElementById("add-holding-btn").style.display = "";
    clearHoldingForm();
};

// 选择日期后自动查询净值
document.getElementById("hf-date").onchange = function () {
    var code = document.getElementById("hf-code").value.trim();
    var date = this.value;
    if (code.length === 6 && date) {
        var navEl = document.getElementById("hf-nav");
        navEl.value = "查询中...";
        fetch(API + "/fund/" + code + "/nav/" + date)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) { navEl.value = ""; navEl.placeholder = d.error; return; }
                navEl.value = d.nav;
                if (!d.exact) navEl.placeholder = d.note;
            }).catch(function () { navEl.value = ""; });
    }
};
document.getElementById("hf-code").oninput = function () {
    var code = this.value.trim();
    var nameEl = document.getElementById("hf-name");
    if (code.length === 6) {
        nameEl.textContent = "查询中...";
        fetch(API + "/fund/" + code)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var label = d.name || "未找到";
                if (_heldCodes.indexOf(code) >= 0) {
                    label += "（已有持仓，将自动合并）";
                }
                nameEl.textContent = label;
            }).catch(function () { nameEl.textContent = "未找到"; });
    } else {
        nameEl.textContent = "";
    }
};

document.getElementById("hf-save").onclick = function () {
    var code = document.getElementById("hf-code").value.trim();
    var date = document.getElementById("hf-date").value;
    var nav = parseFloat(document.getElementById("hf-nav").value);
    var amount = parseFloat(document.getElementById("hf-amount").value) || 0;
    var notes = document.getElementById("hf-notes").value.trim();

    if (!code || !date || !nav) { alert("请填写代码、买入日期和净值"); return; }
    if (isNaN(nav) || nav <= 0) { alert("净值格式错误"); return; }

    fetch(API + "/portfolio/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code, buy_date: date, buy_nav: nav, buy_amount: amount, notes: notes })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
          if (d.error) { alert(d.error); return; }
          document.getElementById("add-holding-form").style.display = "none";
          document.getElementById("add-holding-btn").style.display = "";
          clearHoldingForm();
          loadPortfolio();
      }).catch(function (e) { alert("保存失败: " + e.message); });
};

function clearHoldingForm() {
    document.getElementById("hf-code").value = "";
    document.getElementById("hf-date").value = "";
    document.getElementById("hf-nav").value = "";
    document.getElementById("hf-amount").value = "";
    document.getElementById("hf-notes").value = "";
    document.getElementById("hf-name").textContent = "";
}

function addHoldingQuick(code) {
    // 快速添加：弹出表单并预填代码
    document.getElementById("add-holding-form").style.display = "block";
    document.getElementById("add-holding-btn").style.display = "none";
    document.getElementById("hf-code").value = code;
    document.getElementById("hf-code").dispatchEvent(new Event("input"));
    document.getElementById("hf-date").focus();
}

// 持仓自动加载
var _heldCodes = [];
loadPortfolio();
loadHistory();
load(false);
