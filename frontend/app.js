const API = "http://localhost:8000/api";

function fmt(v) { if (v === null || v === undefined || isNaN(v)) return "-"; return (v >= 0 ? "+" : "") + v.toFixed(2) + "%"; }
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
    try {
        var res = await fetch(API + "/top20" + (force ? "?refresh=true" : ""));
        clearInterval(timer);
        if (!res.ok) throw new Error("HTTP " + res.status);
        var data = await res.json();
        if (!data.results || !data.results.length) { err.textContent = "暂无符合条件的基金"; err.style.display = "block"; el.style.display = "none"; return; }
        render(data);
        tbl.style.display = ""; el.style.display = "none";
        fr.textContent = data.updated_at + " (" + Math.round((Date.now() - t0) / 1000) + "s)"; fr.className = "fresh";
    } catch (e) {
        clearInterval(timer);
        err.textContent = "加载失败: " + e.message; err.style.display = "block"; el.style.display = "none";
    }
}

function render(data) {
    var h = "";
    data.results.forEach(function (r, i) {
        var n = i + 1, top = n <= 3 ? " top" : "";
        h += '<tr class="clickable" onclick="showDetail(\'' + r.code + '\', \'' + r.name.replace(/'/g, "\\'") + '\')">';
        h += '<td class="rnk' + n + top + '">' + n + '</td>';
        h += '<td class="code">' + r.code + '</td>';
        h += '<td class="name" title="' + r.name + '">' + r.name + '</td>';
        h += '<td class="' + sclr(r.score) + ' bold">' + r.score + '</td>';
        h += '<td class="' + clr(r.ret_5d) + '">' + fmt(r.ret_5d) + '</td>';
        h += '<td class="' + clr(r.ret_20d) + '">' + fmt(r.ret_20d) + '</td>';
        h += '<td class="' + clr(r.ret_1y) + '">' + fmt(r.ret_1y) + '</td>';
        h += '<td>' + r.nav_pct_2y + '%</td>';
        h += '<td class="' + clr(-r.drawdown) + '">' + fmt(-Math.abs(r.drawdown)) + '</td>';
        h += '<td>' + maLabel(r.ma_below) + '</td>';
        h += '<td>' + r.rsi + '</td>';
        h += '<td>' + r.consecutive_down + '天</td>';
        h += '<td>' + warnLabel(r.warning) + '</td>';
        h += '</tr>';
    });
    document.getElementById("tbody").innerHTML = h;
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
    } catch (e) {
        document.getElementById("detail-stats").innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
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
    fetch(API + "/fund/" + d.code + "/advice")
        .then(function (r) { return r.json(); })
        .then(function (adv) {
            if (adv.buy && adv.sell) {
                var h = '<h3>买卖建议</h3>';
                // 买入建议
                var b = adv.buy;
                h += '<div class="advice-card">';
                h += '<div class="advice-title">买入建议：' + b.buy_urgency + '</div>';
                h += '<div class="advice-body">';
                h += '<p>估值状态：<b>' + b.valuation.label + '</b>（分位 ' + b.valuation.pct + '%）</p>';
                h += '<p>建议仓位：<b>' + b.suggested_position + '</b></p>';
                h += '<p>入场计划：' + b.batch_plan + '</p>';
                if (b.entry_points && b.entry_points.length > 0) {
                    h += '<p>参考价位：';
                    b.entry_points.forEach(function (ep) {
                        h += '<span class="tag">' + ep.level + ' ' + ep.price + '（' + ep.label + '）</span> ';
                    });
                    h += '</p>';
                }
                if (b.risk_warnings && b.risk_warnings.length > 0) {
                    h += '<p class="risk">⚠ ';
                    b.risk_warnings.forEach(function (w) { h += w + '<br>'; });
                    h += '</p>';
                }
                h += '</div></div>';

                // 卖出信号
                var s = adv.sell;
                h += '<div class="advice-card">';
                h += '<div class="advice-title">卖出信号：' + s.summary + '</div>';
                h += '<div class="advice-body">';
                if (s.profit_pct !== null && s.profit_pct !== undefined) {
                    h += '<p>持仓盈亏：<b class="' + (s.profit_pct >= 0 ? 'up' : 'down') + '">' + fmt(s.profit_pct) + '</b></p>';
                }
                h += '<p>当前净值：' + s.current_nav + ' | RSI：' + s.rsi + '</p>';
                s.signals.forEach(function (sig) {
                    h += '<p>' + sig.icon + ' <b>' + sig.type + '</b>：' + sig.msg + '</p>';
                });
                h += '</div></div>';
                container.innerHTML = h;
            } else {
                container.innerHTML = '<div class="error">建议加载失败</div>';
            }
        }).catch(function (e) {
            container.innerHTML = '<div class="error">建议加载失败: ' + e.message + '</div>';
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
        return;
    }
    var h = '<div class="summary-cards">';
    h += '<div class="scard"><span class="slbl">总投入</span><span class="sval">¥' + data.total_invested.toLocaleString() + '</span></div>';
    h += '<div class="scard"><span class="slbl">当前市值</span><span class="sval">¥' + data.total_value.toLocaleString() + '</span></div>';
    var pcls = data.total_profit >= 0 ? "up" : "down";
    h += '<div class="scard"><span class="slbl">总盈亏</span><span class="sval ' + pcls + '">' + fmt(data.total_profit_pct) + ' (¥' + Math.round(data.total_profit).toLocaleString() + ')</span></div>';
    h += '<div class="scard"><span class="slbl">持仓数</span><span class="sval">' + data.holdings_count + '只</span></div>';
    h += '</div>';

    // 赛道分布
    if (data.sector_allocation && Object.keys(data.sector_allocation).length > 0) {
        h += '<div class="sector-bar">';
        Object.keys(data.sector_allocation).forEach(function (k) {
            var v = data.sector_allocation[k];
            h += '<span class="sbar-item" title="' + k + ' ' + v.pct + '%">' + k + ' <b>' + v.pct + '%</b></span>';
        });
        h += '</div>';
    }

    // 警告
    if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach(function (w) {
            h += '<div class="warn-msg">⚠ ' + w + '</div>';
        });
    }
    // 再平衡建议
    if (data.rebalance_advice) {
        h += '<div class="rebalance-msg">💡 ' + data.rebalance_advice + '</div>';
    }
    // 卖出优先
    if (data.sell_priority && data.sell_priority.length > 0) {
        h += '<div class="sell-priority">🔴 优先关注卖出：';
        data.sell_priority.forEach(function (sp) {
            h += '<span class="tag r">' + sp.name + '(' + fmt(sp.profit_pct) + ')</span> ';
        });
        h += '</div>';
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
        h += '<td class="code">' + d.code + '</td>';
        h += '<td class="name" title="' + d.name + '">' + d.name + '</td>';
        h += '<td>' + d.buy_date + '</td>';
        h += '<td>' + d.buy_nav + '</td>';
        h += '<td>' + d.current_nav + '</td>';
        h += '<td class="' + (d.profit_pct >= 0 ? 'up' : 'down') + '">' + fmt(d.profit_pct) + '</td>';
        h += '<td><span class="tag">' + d.sector + '</span></td>';
        var sa = d.sell_action_level;
        var scls = sa >= 3 ? 'r' : sa >= 2 ? 'o' : sa >= 1 ? 'y' : 'g';
        h += '<td><span class="tag ' + scls + '">' + d.sell_summary + '</span></td>';
        h += '<td><button class="btn-ghost-sm" onclick="deleteHolding(' + d.id + ')">删除</button></td>';
        h += '</tr>';
    });
    h += '</tbody></table>';
    el.innerHTML = h;
}

function deleteHolding(id) {
    if (!confirm("确认删除这笔持仓记录？")) return;
    fetch(API + "/portfolio/" + id, { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function () { loadPortfolio(); });
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
      });
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
loadPortfolio();
load(false);
