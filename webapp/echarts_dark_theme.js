(function () {
    // 统计图表共用的暗色主题（ECharts registerTheme 使用）。
    // 与 webapp/echarts_light_theme.js 保持相同的结构性字段。
    window.__echartsChartTheme = {
        color: ["#64b5f6", "#ce93d8", "#ffd54f", "#22d3ee", "#81c784", "#1565c0"],
        backgroundColor: "#1a1a2e",
        textStyle: { color: "#9aa0b0" },
        grid: { borderColor: "#2a2a3e", containLabel: true },
        categoryAxis: {
            axisLine: { lineStyle: { color: "#3a3a4e" } },
            axisLabel: { color: "#6a6f7e" },
            splitLine: { lineStyle: { color: "#2a2a3e" } },
        },
        valueAxis: {
            axisLine: { show: false },
            axisLabel: { color: "#6a6f7e" },
            splitLine: { lineStyle: { color: "#2a2a3e" } },
        },
        legend: { textStyle: { color: "#b6bccb" } },
        tooltip: {
            backgroundColor: "#39394e",
            borderColor: "#555",
            textStyle: { color: "#e8e8ee" },
        },
    };

    // 库通过 <script src> 异步加载，本脚本可能先于 echarts 就绪执行。
    // 因此注册逻辑必须可重复调用：后端注入顺序是库 → 主题 → 渲染，但
    // 主题执行时 window.echarts 可能尚不存在，故由渲染脚本在 init 前
    // 再次调用 __registerAlasStatTheme()，确保主题一定注册成功。
    var registered = false;
    function register() {
        if (!window.echarts || !window.__echartsChartTheme || registered) return;
        if (window.echarts.registerTheme) {
            window.echarts.registerTheme("alas-stat-dark", window.__echartsChartTheme);
            registered = true;
        }
    }
    window.__registerAlasStatTheme = register;
    register();
})();
