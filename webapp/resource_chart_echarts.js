(function () {
    // 资源变化图：每条资源使用独立逻辑 Y 轴，避免数量级互相压平。
    function findContainer(chartId) { return document.getElementById(chartId + "_echarts"); }
    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
            return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch];
        });
    }
    function validValues(values) {
        return (values || []).filter(function (v) { return v !== null && v !== undefined; });
    }
    function rangeForSeries(series) {
        var values = validValues(series.data);
        var min = values.length ? Math.min.apply(Math, values) : 0;
        var max = values.length ? Math.max.apply(Math, values) : 100;
        if (min === max) max = min + 100;
        var extra = Math.max((max - min) * 0.2, max * 0.1, 1);
        return { min: Math.max(0, min - extra), max: max + extra };
    }
    function compactAxisLabel(value) {
        var abs = Math.abs(value);
        if (abs >= 1000000) return (value / 1000000).toFixed(abs >= 10000000 ? 0 : 1).replace(/\.0$/, "") + "m";
        if (abs >= 1000) return (value / 1000).toFixed(abs >= 100000 ? 0 : 1).replace(/\.0$/, "") + "k";
        if (abs >= 10) return String(Math.round(value));
        return Number(value.toFixed(1)).toString();
    }
    function neutralAxis(seriesData, selected) {
        var min = Infinity, max = -Infinity;
        seriesData.forEach(function (series) {
            if (selected && selected[series.name] === false) return;
            var range = rangeForSeries(series);
            min = Math.min(min, range.min);
            max = Math.max(max, range.max);
        });
        if (!isFinite(min) || !isFinite(max)) { min = 0; max = 100; }
        return {
            type: "value", min: min, max: max,
            axisLabel: { color: "#6a6f7e", formatter: compactAxisLabel },
            axisLine: { show: false },
            splitLine: { show: true, lineStyle: { color: "#2a2a3e" } },
        };
    }
    function axisForSeries(series, rightOffset, compact) {
        var range = rangeForSeries(series);
        var special = series.key === "ActionPoint" || series.key === "YellowCoin" || series.key === "PurpleCoin";
        return {
            type: "value", min: range.min, max: range.max,
            position: special ? "right" : "left",
            offset: special ? rightOffset : 0,
            show: special && !compact,
            axisLabel: { show: special && !compact, color: series.color, formatter: compactAxisLabel },
            axisLine: { show: special && !compact, lineStyle: { color: series.color } },
            splitLine: { show: false },
        };
    }
    function tooltipFormatter(data) {
        return function (params) {
            var list = Array.isArray(params) ? params : [params];
            var point = list[0];
            if (!point || point.dataIndex == null) return "";
            var idx = point.dataIndex;
            var rows = ["<div style='font-weight:600;margin-bottom:4px'>" + escapeHtml(data.labels[idx]) + "</div>"];
            list.forEach(function (item) {
                var s = (data.series || []).filter(function (candidate) { return candidate.name === item.seriesName; })[0];
                if (s && s.data && s.data[idx] != null) rows.push(escapeHtml(s.name) + ": <b style='color:" + s.color + "'>" + Number(s.data[idx]).toLocaleString() + "</b>");
            });
            return rows.join("<br>");
        };
    }
    function render(chartId, data) {
        if (!data || !Array.isArray(data.labels) || !data.labels.length || !window.echarts) return;
        if (window.__registerAlasStatTheme) window.__registerAlasStatTheme();
        window.__resourceChartInstances = window.__resourceChartInstances || {};
        window.__resourceChartCleanups = window.__resourceChartCleanups || {};
        if (window.__resourceChartCleanups[chartId]) window.__resourceChartCleanups[chartId]();
        var el = findContainer(chartId);
        if (!el) return;
        var seriesData = (data.series || []).filter(function (s) { return validValues(s.data).length; });
        if (!seriesData.length) return;
        var compact = el.clientWidth < 640;
        var selectedState = {};
        function buildAxes() {
            var rightAxisCount = 0;
            var nextAxes = [neutralAxis(seriesData, selectedState)];
            seriesData.forEach(function (series) {
                var selected = selectedState[series.name] !== false;
                var special = series.key === "ActionPoint" || series.key === "YellowCoin" || series.key === "PurpleCoin";
                var axis = axisForSeries(series, special ? rightAxisCount * 44 : 0, compact);
                if (special && selected) rightAxisCount += 1;
                axis.show = special && selected && !compact;
                nextAxes.push(axis);
            });
            return nextAxes;
        }
        function visibleRightAxisCount() {
            return seriesData.filter(function (series) {
                var special = series.key === "ActionPoint" || series.key === "YellowCoin" || series.key === "PurpleCoin";
                return special && selectedState[series.name] !== false;
            }).length;
        }
        function chartGrid() {
            if (compact) return { left: 54, right: 12, top: 66, bottom: 58, containLabel: false };
            var rightAxisCount = visibleRightAxisCount();
            return {
                left: 60,
                right: rightAxisCount ? 68 + (rightAxisCount - 1) * 44 : 20,
                top: 42,
                bottom: 58,
                containLabel: false,
            };
        }
        function chartLegend() {
            return { top: 0, left: 0, right: compact ? 8 : 104, type: "scroll", data: seriesData.map(function (s) { return s.name; }) };
        }
        function chartToolbox() {
            return { right: 8, top: compact ? 26 : 4, feature: { dataZoom: { yAxisIndex: "none" }, restore: {} } };
        }
        var optionSeries = seriesData.map(function (s, i) {
            return { name: s.name, type: "line", data: s.data, yAxisIndex: i + 1, symbol: "none", connectNulls: false, clip: true, lineStyle: { width: 1.5, color: s.color }, itemStyle: { color: s.color }, __seriesKey: s.key };
        });
        var chart = echarts.init(el, "alas-stat-dark");
        window.__resourceChartInstances[chartId] = chart;
        chart.setOption({
            backgroundColor: "transparent", animation: false,
            tooltip: { trigger: "axis", axisPointer: { type: "cross" }, confine: true, formatter: tooltipFormatter({labels: data.labels, series: seriesData}) },
            legend: chartLegend(),
            toolbox: chartToolbox(),
            grid: chartGrid(),
            xAxis: { type: "category", data: data.labels, boundaryGap: false, axisLabel: { formatter: function (v) { return String(v).length > 16 ? String(v).slice(0, 16) + "…" : v; } } },
            yAxis: buildAxes(),
            dataZoom: [{ type: "inside", xAxisIndex: 0, filterMode: "empty" }, { type: "slider", xAxisIndex: 0, height: 18, bottom: 8, filterMode: "empty" }],
            series: optionSeries,
        }, true);
        chart.on("legendselectchanged", function (event) {
            selectedState = event.selected;
            chart.setOption({ grid: chartGrid(), yAxis: buildAxes() });
        });
        var observer = null;
        var resize = function () {
            if (chart.isDisposed()) return;
            chart.resize();
            var nextCompact = el.clientWidth < 640;
            if (nextCompact !== compact) {
                compact = nextCompact;
                chart.setOption({ grid: chartGrid(), legend: chartLegend(), toolbox: chartToolbox(), yAxis: buildAxes() });
            }
        };
        if (window.ResizeObserver) { observer = new ResizeObserver(resize); observer.observe(el); } else window.addEventListener("resize", resize);
        window.__resourceChartCleanups[chartId] = function () {
            if (observer) observer.disconnect();
            window.removeEventListener("resize", resize);
            if (window.__resourceChartInstances[chartId] === chart) delete window.__resourceChartInstances[chartId];
            if (!chart.isDisposed()) chart.dispose();
            delete window.__resourceChartCleanups[chartId];
        };
    }
    window.__renderResourceChart = function (chartId, payload) {
        var ready = window.__alasEchartsPromise || Promise.resolve(window.echarts);
        ready.then(function () { render(chartId, payload); }).catch(function () {});
    };
})();
