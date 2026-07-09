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
    el.style.display = "block"; el.textContent = "正在分析 " + Math.round((Date.now() - t0) / 1000) + " 秒...";
    err.style.display = "none"; tbl.style.display = "none";
    var t0 = Date.now();
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
        renderCharts(d);
        renderStats(d);
    } catch (e) {
        document.getElementById("detail-stats").innerHTML = '<div class="error">加载失败: ' + e.message + '</div>';
    }
}

function renderCharts(d) {
    var C = chartColors();

    // 净值图：用完整净值历史
    var navDates = d.nav_history.map(function (n) { return n.date; });
    var navs = d.nav_history.map(function (n) { return n.nav; });

    // 信号对齐到净值日期
    var sigMap = {};
    d.signals.forEach(function (s) { sigMap[s.date] = s; });
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

    // RSI + MACD 用信号日期
    var sigDates = d.signals.map(function (s) { return s.date; });
    var rsis = d.signals.map(function (s) { return s.rsi || null; });
    var difs = d.signals.map(function (s) { return s.macd_dif || null; });
    var deas = d.signals.map(function (s) { return s.macd_dea || null; });
    var hists = d.signals.map(function (s) { return s.macd_hist || null; });

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

// 按钮
document.getElementById("refresh-btn").onclick = function () {
    this.textContent = "刷新中..."; this.disabled = true;
    load(true).finally(function () { this.textContent = "刷新数据"; this.disabled = false; }.bind(this));
};

load(false);
