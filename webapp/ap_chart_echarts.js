(function () {
    // 体力变化图：ECharts 折线/K 线实现，保留旧版数据密度和详情信息。
    function findContainer(chartId) { return document.getElementById(chartId + "_echarts"); }
    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
            return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch];
        });
    }
    function hasValues(values) {
        return Array.isArray(values) && values.some(function (v) { return v !== null && v !== undefined; });
    }
    function average(values, end, size) {
        if (end + 1 < size) return "-";
        var total = 0;
        for (var i = end - size + 1; i <= end; i++) total += Number(values[i]);
        return (total / size).toFixed(1);
    }
    function buildAxes(data, chartType, compact) {
        var axes = [{ type: "value", min: 0, scale: true }];
        if (chartType === "line") {
            axes.push(hasValues(data.purpleCoins) ? { type: "value", min: 0, position: "right", show: !compact, axisLabel: { color: "#ce93d8" }, splitLine: { show: false } } : { type: "value", show: false });
            axes.push(hasValues(data.yellowCoins) || hasValues(data.asset) || hasValues(data.distance) ? { type: "value", min: 0, position: "right", offset: 44, show: !compact, axisLabel: { color: "#ffd54f" }, splitLine: { show: false } } : { type: "value", show: false });
        } else {
            axes.push({ type: "value", show: false }); axes.push({ type: "value", show: false });
        }
        return axes;
    }
    function addLineSeries(series, data, key, name, color, yAxisIndex) {
        if (!hasValues(data)) return;
        series.push({ name: name, type: "line", data: data, yAxisIndex: yAxisIndex || 0, symbol: "none", connectNulls: false, clip: true, lineStyle: { width: 1.5, color: color }, itemStyle: { color: color }, emphasis: { focus: "series" }, __seriesKey: key });
    }
    function buildApSeries(data) {
        var series = [];
        if (data.chartType === "candlestick") {
            var candles = [];
            for (var i = 0; i < data.labels.length; i++) candles.push([data.opens[i], data.closes[i], data.lows[i], data.highs[i]]);
            series.push({ name: "体力", type: "candlestick", data: candles, clip: true, itemStyle: { color: "#ef5350", color0: "#26a69a", borderColor: "#ef5350", borderColor0: "#26a69a" }, markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "#ff9800", type: "dashed" }, data: [{ name: "均值", yAxis: data.avg }] }, __seriesKey: "ap" });
            series.push({ name: "MA5", type: "line", data: data.closes.map(function (_, i) { return average(data.closes, i, 5); }), symbol: "none", connectNulls: false, clip: true, lineStyle: { width: 1.2, color: "#ffeb3b" }, __seriesKey: "ma5" });
            series.push({ name: "MA10", type: "line", data: data.closes.map(function (_, i) { return average(data.closes, i, 10); }), symbol: "none", connectNulls: false, clip: true, lineStyle: { width: 1.2, color: "#e91e63" }, __seriesKey: "ma10" });
            return series;
        }
        addLineSeries(series, data.ap, "ap", "体力", "#64b5f6", 0);
        series[0].markLine = { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "#ff9800", type: "dashed" }, data: [{ name: "均值", yAxis: data.avg }] };
        addLineSeries(series, data.purpleCoins, "purpleCoins", "紫币", "#ce93d8", 1);
        addLineSeries(series, data.yellowCoins, "yellowCoins", "黄币", "#ffd54f", 2);
        addLineSeries(series, data.asset, "asset", "资产", "#81c784", 2);
        addLineSeries(series, data.distance, "distance", "海里数", "#1565c0", 2);
        if (hasValues(data.ap)) {
            var segments = [];
            for (var i = 1; i < data.ap.length; i++) if (data.ap[i] != null && data.ap[i - 1] != null) segments.push([i, data.ap[i - 1], data.ap[i]]);
            series.push({
                id: "ap-change-segments", name: "__ap_segments", type: "custom", data: segments, silent: true, clip: true,
                encode: { x: 0, y: [1, 2] }, tooltip: { show: false }, __seriesKey: "apSegment",
                renderItem: function (params, api) {
                    var end = api.value(0), previous = api.value(1), current = api.value(2);
                    var from = api.coord([end - 1, previous]), to = api.coord([end, current]);
                    return { type: "line", shape: { x1: from[0], y1: from[1], x2: to[0], y2: to[1] }, style: { stroke: current >= previous ? "#ef5350" : "#26a69a", lineWidth: 2 } };
                },
            });
        }
        return series;
    }
    function tooltipFormatter(data, chartType) {
        function changeSuffix(values, idx) {
            if (!values || idx <= 0 || values[idx] == null || values[idx - 1] == null) return "";
            var change = values[idx] - values[idx - 1];
            var color = change >= 0 ? "#ef5350" : "#26a69a";
            return " <span style='color:" + color + "'>(" + (change >= 0 ? "+" : "") + change + ")</span>";
        }
        return function (params) {
            var list = Array.isArray(params) ? params : [params];
            var point = list.filter(function (item) { return item && item.seriesName !== "__ap_segments"; })[0];
            if (!point || point.dataIndex == null) return "";
            var idx = point.dataIndex;
            var visible = {};
            list.forEach(function (item) { if (item) visible[item.seriesName] = true; });
            var rows = ["<div style='font-weight:600;margin-bottom:4px'>" + escapeHtml(data.labels[idx]) + "</div>"];
            if (chartType === "candlestick") {
                var c = data.closes[idx], o = data.opens[idx], h = data.highs[idx], l = data.lows[idx], change = c - o;
                var pct = o ? (change / o * 100).toFixed(1) : "0.0";
                rows.push("开盘: " + o + "　收盘: <b style='color:" + (change >= 0 ? "#ef5350" : "#26a69a") + "'>" + c + "</b>");
                rows.push("最高: " + h + "　最低: " + l);
                rows.push("涨跌: " + (change >= 0 ? "+" : "") + change + " (" + (change >= 0 ? "+" : "") + pct + "%)");
                rows.push("MA5: " + average(data.closes, idx, 5) + "　MA10: " + average(data.closes, idx, 10));
                rows.push("数据点密度: " + (data.counts[idx] == null ? "-" : data.counts[idx]));
            } else {
                if (visible["体力"] && data.ap && data.ap[idx] != null) {
                    var diff = idx > 0 && data.ap[idx - 1] != null ? data.ap[idx] - data.ap[idx - 1] : 0;
                    rows.push("体力: <b style='color:#64b5f6'>" + data.ap[idx] + "</b>　单次变化: " + (diff >= 0 ? "+" : "") + diff);
                    if (data.isDetailMode && data.sources && data.sources[idx]) {
                        var source = data.sources[idx];
                        var sourceColor = source === "cl1" ? "#64b5f6" : source === "meow" ? "#ff9800" : "#b6bccb";
                        rows.push("来源: <b style='color:" + sourceColor + "'>" + escapeHtml(source) + "</b>");
                    }
                }
                [["purpleCoins","紫币","#ce93d8"],["yellowCoins","黄币","#ffd54f"],["asset","资产","#81c784"],["distance","海里数","#1565c0"]].forEach(function (item) {
                    var values = data[item[0]];
                    if (visible[item[1]] && values && values[idx] != null) rows.push(item[1] + ": <b style='color:" + item[2] + "'>" + values[idx] + "</b>" + (item[0] === "asset" ? "" : changeSuffix(values, idx)));
                });
            }
            return rows.join("<br>");
        };
    }
    function render(chartId, data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length || !window.echarts) return;
        if (window.__registerAlasStatTheme) window.__registerAlasStatTheme();
        window.__apChartInstances = window.__apChartInstances || {};
        window.__apChartCleanups = window.__apChartCleanups || {};
        if (window.__apChartCleanups[chartId]) window.__apChartCleanups[chartId]();
        var el = findContainer(chartId);
        if (!el) return;
        var chart = echarts.init(el, "alas-stat-dark");
        window.__apChartInstances[chartId] = chart;
        var chartType = data.chartType === "candlestick" ? "candlestick" : "line";
        var series = buildApSeries(data);
        var visibleLegend = series.filter(function (s) { return s.__seriesKey !== "apSegment"; }).map(function (s) { return s.name; });
        var compact = el.clientWidth < 640;
        var selectedState = {};
        function rightAxisVisibility() {
            if (chartType !== "line" || compact) return { purple: false, auxiliary: false };
            return {
                purple: hasValues(data.purpleCoins) && selectedState["紫币"] !== false,
                auxiliary: (
                    (hasValues(data.yellowCoins) && selectedState["黄币"] !== false) ||
                    (hasValues(data.asset) && selectedState["资产"] !== false) ||
                    (hasValues(data.distance) && selectedState["海里数"] !== false)
                ),
            };
        }
        function buildVisibleAxes() {
            var nextAxes = buildAxes(data, chartType, compact);
            nextAxes[0].show = chartType === "line"
                ? selectedState["体力"] !== false
                : selectedState["体力"] !== false || selectedState["MA5"] !== false || selectedState["MA10"] !== false;
            if (chartType === "line") {
                var visibility = rightAxisVisibility();
                nextAxes[1].show = visibility.purple;
                nextAxes[2].show = visibility.auxiliary;
                nextAxes[2].offset = visibility.purple && visibility.auxiliary ? 44 : 0;
            }
            return nextAxes;
        }
        function chartGrid() {
            if (compact) return { left: 54, right: 12, top: 66, bottom: 58, containLabel: false };
            var visibility = rightAxisVisibility();
            var rightAxisCount = (visibility.purple ? 1 : 0) + (visibility.auxiliary ? 1 : 0);
            return {
                left: 60,
                right: rightAxisCount ? 68 + (rightAxisCount - 1) * 44 : 20,
                top: 42,
                bottom: 58,
                containLabel: false,
            };
        }
        function chartLegend() {
            return { top: 0, left: 0, right: compact ? 8 : 104, type: "scroll", data: visibleLegend };
        }
        function chartToolbox() {
            return { right: 8, top: compact ? 26 : 4, feature: { dataZoom: { yAxisIndex: "none" }, restore: {} } };
        }
        chart.setOption({
            backgroundColor: "transparent", animation: false,
            tooltip: { trigger: "axis", axisPointer: { type: "cross" }, confine: true, formatter: tooltipFormatter(data, chartType) },
            legend: chartLegend(),
            toolbox: chartToolbox(),
            grid: chartGrid(),
            xAxis: { type: "category", data: data.labels, boundaryGap: chartType === "candlestick", axisLabel: { formatter: function (v) { return String(v).length > 16 ? String(v).slice(0, 16) + "…" : v; } } },
            yAxis: buildVisibleAxes(),
            dataZoom: [{ type: "inside", xAxisIndex: 0, filterMode: "empty" }, { type: "slider", xAxisIndex: 0, height: 18, bottom: 8, filterMode: "empty" }],
            series: series,
        }, true);
        chart.on("legendselectchanged", function (event) {
            selectedState = event.selected;
            var segmentSeries = series.filter(function (item) { return item.__seriesKey === "apSegment"; })[0];
            chart.setOption({
                grid: chartGrid(),
                yAxis: buildVisibleAxes(),
                series: segmentSeries ? [{ id: "ap-change-segments", data: event.selected["体力"] === false ? [] : segmentSeries.data }] : [],
            });
        });
        var observer = null;
        var resize = function () {
            if (chart.isDisposed()) return;
            chart.resize();
            var nextCompact = el.clientWidth < 640;
            if (nextCompact !== compact) {
                compact = nextCompact;
                chart.setOption({ grid: chartGrid(), legend: chartLegend(), toolbox: chartToolbox(), yAxis: buildVisibleAxes() });
            }
        };
        if (window.ResizeObserver) { observer = new ResizeObserver(resize); observer.observe(el); } else window.addEventListener("resize", resize);
        window.__apChartCleanups[chartId] = function () {
            if (observer) observer.disconnect();
            window.removeEventListener("resize", resize);
            if (window.__apChartInstances[chartId] === chart) delete window.__apChartInstances[chartId];
            if (!chart.isDisposed()) chart.dispose();
            delete window.__apChartCleanups[chartId];
        };
    }
    window.__renderApChart = function (chartId, payload) {
        var ready = window.__alasEchartsPromise || Promise.resolve(window.echarts);
        ready.then(function () { render(chartId, payload); }).catch(function () {});
    };
})();
