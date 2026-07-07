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
        h += '<tr>';
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

document.getElementById("refresh-btn").onclick = function () {
    this.textContent = "刷新中..."; this.disabled = true;
    load(true).finally(function () { this.textContent = "刷新数据"; this.disabled = false; }.bind(this));
};

load(false);
