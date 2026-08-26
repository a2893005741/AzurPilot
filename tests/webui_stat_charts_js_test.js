const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

async function render(file, functionName, payload) {
    const calls = [];
    const handlers = {};
    const chart = {
        setOption(option) { calls.push(option); },
        on(name, handler) { handlers[name] = handler; },
        isDisposed() { return false; },
        dispose() {},
        resize() {},
    };
    const context = {
        Promise,
        console,
        document: { getElementById() { return {}; } },
        echarts: { init() { return chart; } },
        ResizeObserver: class {
            observe() {}
            disconnect() {}
        },
        addEventListener() {},
        removeEventListener() {},
    };
    context.window = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(file, "utf8"), context);
    context[functionName]("chart", payload);
    await new Promise((resolve) => setImmediate(resolve));
    assert.ok(calls.length, file + " did not call setOption");
    return { option: calls[0], calls, handlers };
}

(async function () {
    const apBase = {
        labels: ["10:00", "10:30"],
        opens: [], highs: [], lows: [], closes: [], counts: [],
        ap: [100, 120], apTs: [1, 2], sources: ["cl1", "meow"],
        purpleCoins: [20, 21], yellowCoins: [1000, 1100],
        asset: [1.5, 1.6], assetTs: [1, 2], distance: [10, 12],
        avg: 110, isDetailMode: true,
    };
    const apLine = await render(
        "webapp/ap_chart_echarts.js",
        "__renderApChart",
        Object.assign({ chartType: "line" }, apBase),
    );
    assert.strictEqual(apLine.option.yAxis.length, 3);
    assert.strictEqual(apLine.option.yAxis[0].name, undefined);
    assert.strictEqual(apLine.option.grid.left, 60);
    assert.strictEqual(apLine.option.grid.right, 112);
    assert.strictEqual(apLine.option.grid.containLabel, false);
    assert.ok(apLine.option.series.some((series) => series.type === "custom"));
    assert.ok(apLine.option.series.every((series) => series.clip === true));
    assert.ok(apLine.option.dataZoom.every((zoom) => zoom.filterMode === "empty"));
    assert.ok(apLine.option.series[0].markLine);
    assert.ok(apLine.handlers.legendselectchanged);
    apLine.handlers.legendselectchanged({ selected: { "体力": false } });
    assert.deepStrictEqual(Array.from(apLine.calls[1].series[0].data), []);
    apLine.handlers.legendselectchanged({ selected: { "体力": true } });
    assert.ok(apLine.calls[2].series[0].data.length);
    apLine.handlers.legendselectchanged({ selected: { "体力": true, "紫币": false, "黄币": true, "资产": true, "海里数": true } });
    assert.strictEqual(apLine.calls[3].grid.right, 68);
    assert.strictEqual(apLine.calls[3].yAxis[2].offset, 0);

    const closes = [100, 110, 120, 115, 125, 130, 135, 140, 145, 150];
    const apCandle = await render(
        "webapp/ap_chart_echarts.js",
        "__renderApChart",
        Object.assign({}, apBase, {
            chartType: "candlestick",
            labels: closes.map((_, index) => String(index)),
            opens: closes.map((value) => value - 5),
            highs: closes.map((value) => value + 5),
            lows: closes.map((value) => value - 10),
            closes,
            counts: closes.map(() => 2),
            ap: [],
        }),
    );
    assert.deepStrictEqual(
        Array.from(apCandle.option.series, (series) => series.name),
        ["体力", "MA5", "MA10"],
    );
    assert.strictEqual(apCandle.option.grid.right, 20);
    assert.ok(!apCandle.option.series.some((series) => series.type === "bar"));

    const resource = await render(
        "webapp/resource_chart_echarts.js",
        "__renderResourceChart",
        {
            labels: ["10:00", "10:30"],
            series: [
                { key: "Oil", name: "Oil", color: "#f00", data: [1000, 1100] },
                { key: "Coin", name: "Coin", color: "#ff0", data: [100000, 101000] },
                { key: "ActionPoint", name: "AP", color: "#00f", data: [100, 120] },
                { key: "YellowCoin", name: "YC", color: "#fa0", data: [2000, 2100] },
                { key: "PurpleCoin", name: "PC", color: "#a0f", data: [10, 12] },
            ],
        },
    );
    assert.strictEqual(resource.option.yAxis.length, 6);
    assert.strictEqual(resource.option.grid.left, 60);
    assert.strictEqual(resource.option.grid.right, 156);
    assert.strictEqual(resource.option.grid.containLabel, false);
    assert.strictEqual(resource.option.yAxis[0].axisLabel.color, "#6a6f7e");
    assert.strictEqual(resource.option.yAxis[0].splitLine.show, true);
    assert.deepStrictEqual(
        Array.from(resource.option.series, (series) => series.yAxisIndex),
        [1, 2, 3, 4, 5],
    );
    assert.deepStrictEqual(
        Array.from(resource.option.yAxis.slice(3), (axis) => axis.offset),
        [0, 44, 88],
    );
    assert.strictEqual(resource.option.yAxis[3].axisLabel.formatter(5.399999999), "5.4");
    assert.strictEqual(resource.option.yAxis[4].axisLabel.formatter(125427.5), "125k");
    assert.ok(resource.option.series.every((series) => series.connectNulls === false));
    assert.ok(resource.option.series.every((series) => series.clip === true));
    assert.ok(resource.option.dataZoom.every((zoom) => zoom.filterMode === "empty"));
    assert.ok(resource.handlers.legendselectchanged);
    resource.handlers.legendselectchanged({ selected: { Oil: true, Coin: true, AP: true, YC: false, PC: false } });
    assert.strictEqual(resource.calls[1].grid.right, 68);

    const lifecycleCharts = [];
    let disconnected = 0;
    const lifecycleElement = { clientWidth: 1000 };
    const lifecycleContext = {
        Promise,
        console,
        document: { getElementById() { return lifecycleElement; } },
        echarts: {
            init() {
                const instance = {
                    disposed: false,
                    setOption() {},
                    on() {},
                    isDisposed() { return this.disposed; },
                    dispose() { this.disposed = true; },
                    resize() {},
                };
                lifecycleCharts.push(instance);
                return instance;
            },
        },
        ResizeObserver: class {
            observe() {}
            disconnect() { disconnected += 1; }
        },
        addEventListener() {},
        removeEventListener() {},
    };
    lifecycleContext.window = lifecycleContext;
    vm.createContext(lifecycleContext);
    vm.runInContext(fs.readFileSync("webapp/ap_chart_echarts.js", "utf8"), lifecycleContext);
    vm.runInContext(fs.readFileSync("webapp/resource_chart_echarts.js", "utf8"), lifecycleContext);
    lifecycleContext.__renderApChart("ap", Object.assign({ chartType: "line" }, apBase));
    lifecycleContext.__renderResourceChart("resource", {
        labels: ["10:00"],
        series: [{ key: "Oil", name: "Oil", color: "#f00", data: [1000] }],
    });
    await new Promise((resolve) => setImmediate(resolve));
    const resourceInstance = lifecycleContext.__resourceChartInstances.resource;
    lifecycleContext.__renderApChart("ap", Object.assign({ chartType: "line" }, apBase));
    await new Promise((resolve) => setImmediate(resolve));
    assert.strictEqual(lifecycleCharts.length, 3);
    assert.strictEqual(lifecycleCharts[0].disposed, true);
    assert.strictEqual(disconnected, 1);
    assert.strictEqual(lifecycleContext.__resourceChartInstances.resource, resourceInstance);
    assert.strictEqual(resourceInstance.disposed, false);
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
