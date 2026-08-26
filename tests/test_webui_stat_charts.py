import inspect
import shutil
import subprocess
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from module.webui.app_stat_action_point import ActionPointStatisticsMixin
from module.webui.app_stat_chart import ChartInjectionMixin
from module.webui.app_stat_resource import ResourceStatisticsMixin
from module.webui.fastapi import asgi_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _ActionPointHarness(ActionPointStatisticsMixin):
    cleanup_client_resources = staticmethod(lambda *_args: None)

    def __init__(self):
        self.toolbar_calls = []

    def _render_ap_chart_toolbar(self, current_view, chart_id):
        self.toolbar_calls.append((current_view, chart_id))


class _ResourceHarness(ResourceStatisticsMixin):
    cleanup_client_resources = staticmethod(lambda *_args: None)


class TestStatisticsChartPayloads(unittest.TestCase):
    def setUp(self):
        self.ap = _ActionPointHarness()
        self.points = [
            {"dt": datetime(2026, 8, 26, 10, 0), "ap": 100, "source": "cl1"},
            {"dt": datetime(2026, 8, 26, 10, 30), "ap": 120, "source": "meow"},
        ]

    def test_asset_builder_preserves_legacy_signature(self):
        self.assertEqual(
            "(self)",
            str(inspect.signature(ActionPointStatisticsMixin._render_ap_chart)),
        )
        self.assertEqual(
            "(self)",
            str(inspect.signature(ResourceStatisticsMixin._render_resource_chart)),
        )
        self.assertEqual(
            "(self, asset_timeline, current_view)",
            str(inspect.signature(ActionPointStatisticsMixin._build_ap_chart_asset_data)),
        )
        self.assertEqual(
            "(html, js_code)",
            str(inspect.signature(ResourceStatisticsMixin._output_resource_chart)),
        )

    def test_all_ap_views_keep_expected_payload_fields(self):
        with (
            patch("module.webui.app_stat_action_point.current_time", return_value=datetime(2026, 8, 26, 12, 0)),
            patch("module.webui.app_stat_action_point.t", side_effect=lambda key, **_kwargs: key),
        ):
            for view in ("line", "detail", "day", "month"):
                with self.subTest(view=view):
                    self.ap._ap_chart_view = view
                    data = self.ap._build_ap_chart_series(self.points)
                    self.assertIsNotNone(data)
                    self.assertIn("ap_ts", data)
                    self.assertIn("detail_sources", data)
                    if view in ("line", "detail"):
                        self.assertEqual([100, 120], data["ap_list"])
                        self.assertEqual(["cl1", "meow"], data["detail_sources"])
                    else:
                        self.assertEqual(1, len(data["closes"]))
                        self.assertEqual([2], data["counts"])

    def test_asset_payload_keeps_values_and_timestamps(self):
        result = self.ap._build_ap_chart_asset_data(
            [
                {"ts": "invalid", "asset": 9.9},
                {"ts": "2026-08-26T10:00:00", "asset": 1.5},
                {"ts": "2026-08-26T10:30:00", "asset": 2.5},
            ],
            "line",
        )
        self.assertEqual([1.5, 2.5], result["asset_list"])
        self.assertEqual(2, len(result["asset_ts_list"]))

    def test_invalid_ap_timestamp_is_ignored(self):
        result = self.ap._normalize_ap_chart_points(
            [
                {"ts": "invalid", "ap": 999},
                {"ts": "2026-08-26T10:00:00", "ap": 100},
            ]
        )
        self.assertEqual([100], [point["ap"] for point in result])

    def test_alignment_keeps_points_outside_auxiliary_range_null(self):
        raw_points = [
            {"dt": datetime(2026, 8, 26, 10, 0), "value": 100},
            {"dt": datetime(2026, 8, 26, 11, 0), "value": 200},
        ]
        chart_points = [
            {"dt": datetime(2026, 8, 26, 9, 30)},
            {"dt": datetime(2026, 8, 26, 10, 20)},
            {"dt": datetime(2026, 8, 26, 10, 50)},
            {"dt": datetime(2026, 8, 26, 11, 30)},
        ]
        aligned = self.ap._align_ap_timeline(raw_points, chart_points)
        self.assertEqual(
            [None, 100, 200, None],
            [point["value"] if point is not None else None for point in aligned],
        )

    def test_coin_alignment_does_not_extend_first_or_last_snapshot(self):
        chart_points = [
            {"dt": datetime(2026, 8, 26, hour)} for hour in (9, 10, 11, 12)
        ]
        result = self.ap._build_ap_chart_coins_data(
            [
                {
                    "ts": "2026-08-26T10:00:00",
                    "yellow_coins": 100,
                    "purple_coins": 10,
                },
                {
                    "ts": "2026-08-26T11:00:00",
                    "yellow_coins": 200,
                    "purple_coins": 20,
                },
            ],
            chart_points,
            "line",
        )
        self.assertEqual([None, 100, 200, None], result["yellow_coins_list"])
        self.assertEqual([None, 10, 20, None], result["purple_coins_list"])

    def test_render_payload_contains_detail_and_auxiliary_fields(self):
        with (
            patch("module.webui.app_stat_action_point.current_time", return_value=datetime(2026, 8, 26, 12, 0)),
            patch("module.webui.app_stat_action_point.t", side_effect=lambda key, **_kwargs: key),
            patch("module.webui.app_stat_action_point.use_scope", side_effect=lambda *_args, **_kwargs: nullcontext()),
            patch("module.webui.app_stat_action_point.put_html"),
            patch.object(self.ap, "_inject_chart_scripts") as inject,
        ):
            for view in ("line", "detail", "day", "month"):
                with self.subTest(view=view):
                    self.ap._ap_chart_view = view
                    chart_data = self.ap._build_ap_chart_series(self.points)
                    self.ap._render_ap_chart_content(
                        chart_data,
                        {
                            "yellow_coins_list": [1000, 1100] if view in ("line", "detail") else [],
                            "purple_coins_list": [10, 11] if view in ("line", "detail") else [],
                            "distance_list": [5, 6] if view in ("line", "detail") else [],
                            "asset_list": [1.5, 1.6] if view in ("line", "detail") else [],
                            "asset_ts_list": [1, 2] if view in ("line", "detail") else [],
                            "coins_stats_html": "",
                            "coins_legend_html": "",
                        },
                    )
                    payload = inject.call_args.kwargs["payload"]
                    expected_type = "candlestick" if view in ("day", "month") else "line"
                    self.assertEqual(view, payload["view"])
                    self.assertEqual(expected_type, payload["chartType"])
                    if view in ("line", "detail"):
                        self.assertEqual(["cl1", "meow"], payload["sources"])
                        self.assertEqual(2, len(payload["apTs"]))
                        self.assertEqual([1.5, 1.6], payload["asset"])
                    else:
                        self.assertEqual([2], payload["counts"])
        self.assertEqual(4, inject.call_count)
        self.assertEqual(
            ["line", "detail", "day", "month"],
            [view for view, _chart_id in self.ap.toolbar_calls],
        )

    def test_resource_payload_retains_stable_keys(self):
        resource = _ResourceHarness()
        with (
            patch("module.webui.app_stat_resource.t", side_effect=lambda key, **_kwargs: key),
            patch("module.webui.app_stat_resource.read_webapp_template", return_value="{chart_id}|{title}|{stats_html}"),
        ):
            labels, series_map = resource._build_resource_series(
                [
                    {"ts": "invalid", "oil": 9999},
                    {"ts": "2026-08-26T10:00:00", "oil": 1000, "action_point": 100},
                ]
            )
            _, chart_request = resource._build_resource_chart_content(labels, series_map)
            payload = chart_request["payload"]
        self.assertEqual("Oil", payload["series"][0]["key"])
        self.assertEqual(["08-26 10:00"], labels)
        self.assertIn("ActionPoint", [item["key"] for item in payload["series"]])
        self.assertIsNone(payload["series"][1]["data"][0])


class TestStatisticsChartAssets(unittest.TestCase):
    def test_loader_uses_single_versioned_promise(self):
        chart = ChartInjectionMixin()
        calls = []
        with (
            patch("module.webui.app_stat_chart.run_js", side_effect=calls.append),
            patch("module.webui.app_stat_chart.read_webapp_template", return_value=""),
        ):
            chart._inject_echarts("")
        script = "".join(calls)
        self.assertIn("window.__alasEchartsPromise", script)
        self.assertIn("var scriptId = 'alas-echarts-lib'", script)
        self.assertIn("getElementById(scriptId)", script)
        self.assertIn("echarts.min.js?v=5.5.1", script)
        self.assertIn("window.__alasEchartsPromise = null", script)
        self.assertIn("amdRequire.undef(scriptUrl)", script)

    @unittest.skipUnless(shutil.which("node"), "需要 Node.js 验证共享加载器")
    def test_consecutive_chart_injections_append_one_library_script(self):
        calls = []
        with (
            patch("module.webui.app_stat_chart.run_js", side_effect=calls.append),
            patch("module.webui.app_stat_chart.read_webapp_template", return_value=""),
        ):
            for render_fn in ("__renderApChart", "__renderResourceChart"):
                ChartInjectionMixin._inject_chart_scripts(
                    chart_id=render_fn,
                    payload={"labels": ["10:00"]},
                    render_fn=render_fn,
                    render_script="",
                )

        node_program = r"""
const vm = require("vm");
let appendCount = 0;
const elements = {};
const context = {
    Promise,
    document: {
        getElementById(id) { return elements[id] || null; },
        createElement() {
            return {
                addEventListener() {},
                remove() {},
            };
        },
        head: {
            appendChild(element) {
                appendCount += 1;
                elements[element.id] = element;
            },
        },
    },
};
context.window = context;
vm.runInNewContext(process.argv[1], context);
vm.runInNewContext(process.argv[2], context);
if (appendCount !== 1) throw new Error(`expected one script, got ${appendCount}`);
"""
        subprocess.run(
            ["node", "-e", node_program, calls[0], calls[4]],
            cwd=PROJECT_ROOT,
            check=True,
        )

    @unittest.skipUnless(shutil.which("node"), "需要 Node.js 验证 AMD 加载器")
    def test_loader_exposes_requirejs_module_on_window(self):
        calls = []
        with patch("module.webui.app_stat_chart.run_js", side_effect=calls.append):
            ChartInjectionMixin._inject_echarts("")

        node_program = r"""
const vm = require("vm");
let requireCount = 0;
const elements = {};
const context = {
    Promise,
    Error,
    document: {
        getElementById(id) { return elements[id] || null; },
        querySelector(selector) {
            return selector.includes("data-requiremodule") ? elements.amd : null;
        },
    },
};
context.window = context;
context.define = function () {};
context.define.amd = {};
context.require = function (dependencies, resolve) {
    requireCount += 1;
    elements.amd = { id: "", remove() {} };
    resolve({ version: "5.5.1" });
};
vm.runInNewContext(process.argv[1], context);
Promise.resolve(context.__alasEchartsPromise).then(function () {
    if (requireCount !== 1) throw new Error(`expected one AMD load, got ${requireCount}`);
    if (!context.echarts || context.echarts.version !== "5.5.1") {
        throw new Error("AMD export was not exposed as window.echarts");
    }
    if (elements.amd.id !== "alas-echarts-lib") {
        throw new Error("AMD script did not receive the shared DOM id");
    }
}).catch(function (error) {
    console.error(error);
    process.exitCode = 1;
});
"""
        subprocess.run(
            ["node", "-e", node_program, calls[0]],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_templates_only_expose_echarts_containers(self):
        for name in ("ap_chart_panel.html", "resource_chart.html"):
            content = (PROJECT_ROOT / "webapp" / name).read_text(encoding="utf-8")
            self.assertIn("_echarts", content)
            self.assertNotIn("<canvas", content)
            self.assertNotIn("-legend-item", content)

    def test_renderers_keep_required_interactions(self):
        ap_script = (PROJECT_ROOT / "webapp" / "ap_chart_echarts.js").read_text(encoding="utf-8")
        resource_script = (PROJECT_ROOT / "webapp" / "resource_chart_echarts.js").read_text(encoding="utf-8")
        for marker in ("MA5", "MA10", "dataZoom", "axisPointer", "来源", "__ap_segments"):
            self.assertIn(marker, ap_script)
        for marker in (
            "yAxisIndex: i",
            "dataZoom",
            "axisPointer",
            'type: "scroll"',
            "compactAxisLabel",
        ):
            self.assertIn(marker, resource_script)

    @unittest.skipUnless(shutil.which("node"), "需要 Node.js 执行图表 option 冒烟测试")
    def test_rendered_echarts_options(self):
        subprocess.run(
            ["node", "tests/webui_stat_charts_js_test.js"],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_local_echarts_551_is_publicly_served(self):
        app = asgi_app(
            {"index": lambda: None},
            cdn=False,
            static_mounts={"/static/assets": str(PROJECT_ROOT / "assets")},
        )
        response = TestClient(app).get(
            "/static/assets/gui/js/echarts.min.js"
        )
        self.assertEqual(200, response.status_code)
        self.assertIn('version="5.5.1"', response.text)


if __name__ == "__main__":
    unittest.main()
