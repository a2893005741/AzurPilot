"""WebUI 统计图表共享的注入能力。

AP（体力）图与资源图复用同一套前端资源注入逻辑：ECharts 库、暗色主题
以及各自的渲染脚本均通过 ``run_js`` 发送，浏览器按到达顺序执行。为避免
两个视图各自维护一份几乎相同的注入代码，这里统一收敛为一个 Mixin。
"""

from module.webui.app_dependencies import (
    json,
    run_js,
)

from module.webui.app_helpers import (
    read_webapp_template,
)

from module.webui.app_types import WebUIMixinBase


class ChartInjectionMixin(WebUIMixinBase):
    """为统计图表提供 ECharts 库、主题与渲染脚本的按需注入。"""

    @staticmethod
    def _inject_echarts(theme_script):
        """按需注入 ECharts 库与共用暗色主题，仅在缺失时执行一次。

        主题脚本使用 ``window.echarts.registerTheme``，但库经由 ``script``
        标签异步加载，主题脚本很可能先于库就绪执行，因此注册逻辑本身是
        可重复调用的；渲染脚本会在 ``echarts.init`` 前再次调用注册函数。

        Args:
            theme_script (str): 主题注册脚本文本（来自 webapp/echarts_dark_theme.js）。
        """
        run_js(
            """
            (function(){
                if (window.echarts || window.__alasEchartsPromise) return;
                window.__alasEchartsPromise = new Promise(function(resolve, reject){
                    var scriptId = 'alas-echarts-lib';
                    var scriptUrl = 'static/assets/gui/js/echarts.min.js?v=5.5.1';
                    function fail(error) {
                        window.__alasEchartsPromise = null;
                        var failed = document.getElementById(scriptId)
                            || document.querySelector(
                                'script[data-requiremodule="' + scriptUrl + '"]'
                            );
                        if (failed) failed.remove();
                        if (amdRequire && typeof amdRequire.undef === 'function') {
                            amdRequire.undef(scriptUrl);
                        }
                        reject(error);
                    }
                    function ready(module) {
                        window.echarts = window.echarts || module;
                        if (!window.echarts) {
                            fail(new Error('ECharts loaded without a browser export'));
                            return;
                        }
                        resolve(window.echarts);
                    }

                    // PyWebIO 页面使用 RequireJS。UMD 包检测到 define.amd 后不会
                    // 写入 window.echarts，必须接收 AMD 导出并显式挂到全局。
                    var amdRequire = window.requirejs || window.require;
                    if (typeof window.define === 'function'
                            && window.define.amd
                            && typeof amdRequire === 'function') {
                        amdRequire([scriptUrl], function(module){
                            var loaded = document.querySelector(
                                'script[data-requiremodule="' + scriptUrl + '"]'
                            );
                            if (loaded && !loaded.id) loaded.id = scriptId;
                            ready(module);
                        }, fail);
                        var pending = document.querySelector(
                            'script[data-requiremodule="' + scriptUrl + '"]'
                        );
                        if (pending && !pending.id) pending.id = scriptId;
                        return;
                    }

                    var existing = document.getElementById(scriptId);
                    if (existing) {
                        existing.addEventListener('load', function(){ ready(window.echarts); }, {once:true});
                        existing.addEventListener('error', fail, {once:true});
                        return;
                    }
                    var s = document.createElement('script');
                    s.id = scriptId;
                    s.src = scriptUrl;
                    s.onload = function(){ ready(window.echarts); };
                    s.onerror = fail;
                    document.head.appendChild(s);
                });
            })();
            """
        )
        run_js(
            "(function(){"
            "if (window.__alasStatThemeLoaded) return;"
            "window.__alasStatThemeLoaded=true;"
            f"{theme_script}"
            "})();"
        )

    @staticmethod
    def _inject_renderer(render_fn, render_script):
        """注入单个图表的渲染脚本，各图表用独立守卫名避免互相覆盖。

        Args:
            render_fn (str): 前端暴露的渲染函数名，如 ``__renderApChart``。
            render_script (str): 渲染脚本文本。
        """
        guard = render_fn + "_started"
        run_js(
            "(function(){"
            f"if (window.{guard}) return;"
            f"window.{guard}=true;"
            f"{render_script}"
            "})();"
        )

    @staticmethod
    def _inject_chart_scripts(chart_id, payload, render_fn, render_script):
        """注入库、主题与渲染脚本，然后下发数据并触发渲染。

        脚本经 ``run_js`` 发送，浏览器按到达顺序定义主题和渲染函数；实际
        渲染统一等待 ``window.__alasEchartsPromise`` 完成。每次调用在闭包中
        捕获自己的图表 ID 与载荷，避免同类图表并发刷新时互相覆盖。

        Args:
            chart_id (str): 图表容器 ID。
            payload (dict): 注入给前端渲染函数的结构化载荷。
            render_fn (str): 前端暴露的渲染函数名。
            render_script (str): 渲染脚本文本。
        """
        json_payload = json.dumps(payload, ensure_ascii=False)
        ChartInjectionMixin._inject_echarts(
            theme_script=read_webapp_template("echarts_dark_theme.js")
        )
        ChartInjectionMixin._inject_renderer(
            render_fn=render_fn, render_script=render_script
        )
        chart_id_json = json.dumps(chart_id, ensure_ascii=False)
        run_js(
            f"(function(payload){{"
            f"(window.__alasEchartsPromise||Promise.resolve(window.echarts))"
            f".then(function(){{if(window.{render_fn})window.{render_fn}("
            f"{chart_id_json},payload);}})"
            f".catch(function(){{if(window.{render_fn})window.{render_fn}("
            f"{chart_id_json},payload);}});"
            f"}})({json_payload});"
        )
