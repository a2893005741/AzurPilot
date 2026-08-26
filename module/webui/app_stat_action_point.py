"""WebUI 体力趋势图的数据装配和图表渲染。"""

from module.webui.app_dependencies import (
    current_time,
    datetime,
    put_button,
    put_html,
    put_text,
    t,
    use_scope,
)

from module.webui.app_helpers import (
    build_muted_notice,
    read_webapp_template,
)

from module.webui.app_stat_chart import ChartInjectionMixin


class ActionPointStatisticsMixin(ChartInjectionMixin):
    """WebUI 体力趋势图的数据装配和图表渲染。"""

    def _load_ap_chart_timelines(self):
        """读取当前实例的行动力、凭证和资产时间线。"""
        from module.statistics.opsi_month import (
            get_ap_timeline,
            get_asset_timeline,
            get_coins_timeline,
        )

        instance_name = getattr(self, "alas_name", None)
        if not instance_name:
            from module.config.utils import alas_instance

            all_instances = alas_instance()
            instance_name = all_instances[0] if all_instances else None
        timeline = get_ap_timeline(instance_name=instance_name)
        coins_timeline = get_coins_timeline(instance_name=instance_name)
        asset_timeline = get_asset_timeline(instance_name=instance_name)
        return timeline, coins_timeline, asset_timeline

    def _render_ap_chart(self):
        self.cleanup_client_resources("__apChartCleanups")
        try:
            timeline, coins_timeline, asset_timeline = self._load_ap_chart_timelines()
        except Exception as e:
            with use_scope("ap_chart", clear=True):
                put_text(t("Gui.Stat.LoadApDataFailed", e=e))
            return

        if not timeline:
            with use_scope("ap_chart", clear=True):
                put_html(build_muted_notice(t("Gui.Stat.NoApData")))
                put_button(
                    t("Gui.Stat.Refresh"), onclick=self._render_ap_chart, color="off"
                )
            return

        raw_points = self._normalize_ap_chart_points(timeline)
        if not raw_points:
            with use_scope("ap_chart", clear=True):
                put_html(build_muted_notice(t("Gui.Stat.NoValidApData")))
            return

        chart_data = self._build_ap_chart_series(raw_points)
        if chart_data is None:
            with use_scope("ap_chart", clear=True):
                put_html(build_muted_notice(t("Gui.Stat.CannotAggregateKline")))
                put_button(
                    t("Gui.Stat.ViewLineShort"),
                    onclick=lambda: (
                        setattr(self, "_ap_chart_view", "line"),
                        self._render_ap_chart(),
                    ),
                    color="off",
                )
            return

        auxiliary_data = self._build_ap_chart_auxiliary_data(
            timeline=timeline,
            coins_timeline=coins_timeline,
            asset_timeline=asset_timeline,
            chart_points=chart_data["chart_points"],
            current_view=chart_data["current_view"],
        )
        self._render_ap_chart_content(chart_data, auxiliary_data)

    @staticmethod
    def _normalize_ap_chart_points(timeline):
        """解析行动力快照并按时间排序。"""
        raw_points = []
        for pt in timeline:
            ts_raw = pt.get("ts", "")
            try:
                dt = datetime.fromisoformat(ts_raw)
            except Exception:
                continue
            raw_points.append(
                {
                    "dt": dt,
                    "ap": int(pt.get("ap_total", pt.get("ap", 0))),
                    "source": pt.get("source", "-"),
                }
            )

        raw_points.sort(key=lambda p: p["dt"])
        return raw_points

    def _build_ap_chart_series(self, raw_points):
        """按当前视图构造折线或 K 线主序列及其摘要。"""
        current_view = getattr(self, "_ap_chart_view", "line")

        labels = []
        opens = []
        highs = []
        lows = []
        closes = []
        counts = []
        ap_list = []
        ap_ts = []
        detail_sources = []
        chart_points = []
        is_detail_mode = False

        today = current_time().date()
        today_points = [p for p in raw_points if p["dt"].date() == today]
        if not today_points and raw_points:
            last_date = raw_points[-1]["dt"].date()
            today_points = [p for p in raw_points if p["dt"].date() == last_date]
            today = last_date

        if current_view == "detail":
            is_detail_mode = True
            if today_points:
                for p in today_points:
                    labels.append(p["dt"].strftime("%H:%M"))
                    ap_list.append(p["ap"])
                    ap_ts.append(int(p["dt"].timestamp() * 1000))
                    detail_sources.append(p.get("source", "-"))
                    chart_points.append(p)
                view_title = t("Gui.Stat.DetailChartTitle")
            else:
                for p in raw_points:
                    labels.append(p["dt"].strftime("%m-%d %H:%M"))
                    ap_list.append(p["ap"])
                    ap_ts.append(int(p["dt"].timestamp() * 1000))
                    detail_sources.append(p.get("source", "-"))
                    chart_points.append(p)
                view_title = t("Gui.Stat.ViewTitleLine")
                is_detail_mode = False
                current_view = "line"
        elif current_view == "line":
            for p in raw_points:
                labels.append(p["dt"].strftime("%m-%d %H:%M"))
                ap_list.append(p["ap"])
                ap_ts.append(int(p["dt"].timestamp() * 1000))
                detail_sources.append(p.get("source", "-"))
                chart_points.append(p)
            view_title = t("Gui.Stat.ViewTitleLine")
        else:
            from collections import OrderedDict

            candles = OrderedDict()
            if current_view == "day":
                for p in today_points if today_points else raw_points[:24]:
                    hour_key = p["dt"].strftime("%H:00")
                    if hour_key not in candles:
                        candles[hour_key] = {
                            "open": p["ap"],
                            "high": p["ap"],
                            "low": p["ap"],
                            "close": p["ap"],
                            "count": 1,
                        }
                    else:
                        c = candles[hour_key]
                        c["high"] = max(c["high"], p["ap"])
                        c["low"] = min(c["low"], p["ap"])
                        c["close"] = p["ap"]
                        c["count"] += 1
                view_title = t("Gui.Stat.ViewTitleDay", day=today.strftime("%m-%d"))
            else:
                for p in raw_points:
                    day_key = p["dt"].strftime("%m-%d")
                    if day_key not in candles:
                        candles[day_key] = {
                            "open": p["ap"],
                            "high": p["ap"],
                            "low": p["ap"],
                            "close": p["ap"],
                            "count": 1,
                        }
                    else:
                        c = candles[day_key]
                        c["high"] = max(c["high"], p["ap"])
                        c["low"] = min(c["low"], p["ap"])
                        c["close"] = p["ap"]
                        c["count"] += 1
                view_title = t("Gui.Stat.ViewTitleMonth")

            if not candles:
                return None
            for k, v in candles.items():
                labels.append(k)
                opens.append(v["open"])
                highs.append(v["high"])
                lows.append(v["low"])
                closes.append(v["close"])
                counts.append(v["count"])

        all_ap = [p["ap"] for p in raw_points]
        ap_max = max(all_ap)
        ap_min = min(all_ap)
        ap_avg = int(sum(all_ap) / len(all_ap))
        ap_cur = all_ap[-1]
        if current_view in ("line", "detail"):
            ap_change = ap_list[-1] - ap_list[0] if len(ap_list) >= 2 else 0
            data_points_text = t("Gui.Stat.DataPointsCount", count=len(labels))
        else:
            ap_change = closes[-1] - opens[0] if len(closes) > 0 else 0
            data_points_text = t("Gui.Stat.CandlesCount", count=len(labels))
        change_color = "#ef5350" if ap_change >= 0 else "#26a69a"
        change_sign = "+" if ap_change >= 0 else ""

        return {
            "current_view": current_view,
            "labels": labels,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "counts": counts,
            "ap_list": ap_list,
            "ap_ts": ap_ts,
            "detail_sources": detail_sources,
            "chart_points": chart_points,
            "is_detail_mode": is_detail_mode,
            "view_title": view_title,
            "ap_cur": ap_cur,
            "ap_change": ap_change,
            "ap_max": ap_max,
            "ap_min": ap_min,
            "ap_avg": ap_avg,
            "data_points_text": data_points_text,
            "change_color": change_color,
            "change_sign": change_sign,
        }

    @staticmethod
    def _align_ap_timeline(raw_points, chart_points):
        """按最近时间戳对齐辅助时间线，覆盖范围外保留空值。"""
        from bisect import bisect_left

        if not chart_points:
            return []
        if not raw_points:
            return [None] * len(chart_points)

        raw_points = sorted(raw_points, key=lambda p: p["dt"])
        raw_times = [point["dt"] for point in raw_points]
        first_time = raw_times[0]
        last_time = raw_times[-1]
        aligned_points = []
        for chart_point in chart_points:
            chart_time = chart_point["dt"]
            if chart_time < first_time or chart_time > last_time:
                aligned_points.append(None)
                continue

            right_idx = bisect_left(raw_times, chart_time)
            if right_idx == 0:
                point_idx = 0
            elif right_idx == len(raw_points):
                point_idx = len(raw_points) - 1
            else:
                left_idx = right_idx - 1
                left_delta = chart_time - raw_times[left_idx]
                right_delta = raw_times[right_idx] - chart_time
                point_idx = right_idx if right_delta <= left_delta else left_idx
            aligned_points.append(raw_points[point_idx])
        return aligned_points

    def _build_ap_chart_auxiliary_data(
        self, timeline, coins_timeline, asset_timeline, chart_points, current_view
    ):
        """分别装配辅助序列，并按既有顺序组合图表载荷。"""
        distance_data = self._build_ap_chart_distance_data(
            timeline, chart_points, current_view
        )
        coins_data = self._build_ap_chart_coins_data(
            coins_timeline, chart_points, current_view
        )
        asset_data = self._build_ap_chart_asset_data(asset_timeline, current_view)
        if asset_data["asset_list"] and chart_points:
            asset_points = [
                {
                    "dt": datetime.fromtimestamp(
                        ts / 1000, tz=chart_points[0]["dt"].tzinfo
                    ),
                    "asset": value,
                }
                for ts, value in zip(
                    asset_data["asset_ts_list"], asset_data["asset_list"]
                )
            ]
            aligned_assets = self._align_ap_timeline(asset_points, chart_points)
            asset_data["asset_list"] = [
                point["asset"] if point is not None else None
                for point in aligned_assets
            ]
            asset_data["asset_ts_list"] = [
                int(point["dt"].timestamp() * 1000) if point is not None else None
                for point in aligned_assets
            ]
        return self._combine_ap_chart_auxiliary_data(
            coins_data, distance_data, asset_data
        )

    def _build_ap_chart_coins_data(self, coins_timeline, chart_points, current_view):
        """解析并对齐黄币、紫币时间线，构造对应统计和图例。"""
        yellow_coins_list = []
        purple_coins_list = []
        stats_html = ""

        if coins_timeline and chart_points and current_view in ("line", "detail"):
            coins_raw_points = []
            for pt in coins_timeline:
                ts_raw = pt.get("ts", "")
                try:
                    dt = datetime.fromisoformat(ts_raw)
                except Exception:
                    continue
                yellow_coins = self._snapshot_int(pt, "yellow_coins")
                purple_coins = self._snapshot_int(pt, "purple_coins")
                if yellow_coins is None and purple_coins is None:
                    continue
                coins_raw_points.append(
                    {
                        "dt": dt,
                        "yellow_coins": yellow_coins,
                        "purple_coins": purple_coins,
                        "source": pt.get("source", "-"),
                    }
                )

            if coins_raw_points:
                for coins_point in self._align_ap_timeline(
                    coins_raw_points, chart_points
                ):
                    if coins_point is None:
                        yellow_coins_list.append(None)
                        purple_coins_list.append(None)
                    else:
                        yellow_coins_list.append(coins_point["yellow_coins"])
                        purple_coins_list.append(coins_point["purple_coins"])

                valid_yellow_coins = [v for v in yellow_coins_list if v is not None]
                valid_purple_coins = [
                    v for v in purple_coins_list if v is not None and v > 0
                ]

                if valid_yellow_coins:
                    yc_cur = valid_yellow_coins[-1]
                    yc_change = (
                        valid_yellow_coins[-1] - valid_yellow_coins[0]
                        if len(valid_yellow_coins) >= 2
                        else 0
                    )
                    yc_change_color = "#ef5350" if yc_change >= 0 else "#26a69a"
                    yc_change_sign = "+" if yc_change >= 0 else ""
                    yc_max = max(valid_yellow_coins)
                    yc_min = min(valid_yellow_coins)

                    stats_html += f'<div style="display:grid; grid-template-columns:150px 100px 90px 90px 90px; gap:8px; margin-bottom:2px; font-size:12px; color:#aaa;"><span>黄币: <b style="color:#ffd54f">{yc_cur}</b></span><span>变化: <b style="color:{yc_change_color}">{yc_change_sign}{yc_change}</b></span><span>最高: <b style="color:#ef5350">{yc_max}</b></span><span>最低: <b style="color:#26a69a">{yc_min}</b></span><span></span></div>'
                if valid_purple_coins:
                    pc_cur = valid_purple_coins[-1]
                    pc_change = (
                        valid_purple_coins[-1] - valid_purple_coins[0]
                        if len(valid_purple_coins) >= 2
                        else 0
                    )
                    pc_change_color = "#ef5350" if pc_change >= 0 else "#26a69a"
                    pc_change_sign = "+" if pc_change >= 0 else ""
                    pc_max = max(valid_purple_coins)
                    pc_min = min(valid_purple_coins)

                    stats_html += f'<div style="display:grid; grid-template-columns:150px 100px 90px 90px 90px; gap:8px; margin-bottom:2px; font-size:12px; color:#aaa;"><span>紫币: <b style="color:#ce93d8">{pc_cur}</b></span><span>变化: <b style="color:{pc_change_color}">{pc_change_sign}{pc_change}</b></span><span>最高: <b style="color:#ef5350">{pc_max}</b></span><span>最低: <b style="color:#26a69a">{pc_min}</b></span><span></span></div>'
        return {
            "yellow_coins_list": yellow_coins_list,
            "purple_coins_list": purple_coins_list,
            "stats_html": stats_html,
            "legend_html": "",
        }

    def _build_ap_chart_distance_data(self, timeline, chart_points, current_view):
        """解析并对齐海里数时间线，构造对应统计和图例。"""
        distance_raw_points = []
        if current_view in ("line", "detail"):
            for pt in timeline:
                distance_val = pt.get("distance")
                if distance_val is not None:
                    ts_raw = pt.get("ts", "")
                    try:
                        distance_dt = datetime.fromisoformat(ts_raw)
                        distance_raw_points.append(
                            {
                                "dt": distance_dt,
                                "distance": int(distance_val),
                            }
                        )
                    except Exception:
                        continue

        distance_list = []
        stats_html = ""
        if distance_raw_points and chart_points and current_view in ("line", "detail"):
            for distance_point in self._align_ap_timeline(
                distance_raw_points, chart_points
            ):
                distance_list.append(
                    distance_point["distance"]
                    if distance_point is not None
                    else None
                )

            if distance_list:
                valid_distance = [v for v in distance_list if v is not None]
                if valid_distance:
                    d_cur = valid_distance[-1]
                    d_change = (
                        valid_distance[-1] - valid_distance[0]
                        if len(valid_distance) >= 2
                        else 0
                    )
                    d_change_color = "#ef5350" if d_change >= 0 else "#26a69a"
                    d_change_sign = "+" if d_change >= 0 else ""
                    d_max = max(valid_distance)
                    d_min = min(valid_distance)

                    stats_html += f'<div style="display:grid; grid-template-columns:150px 100px 90px 90px 90px; gap:8px; margin-bottom:2px; font-size:12px; color:#aaa;"><span>海里数: <b style="color:#1565c0">{d_cur}</b></span><span>变化: <b style="color:{d_change_color}">{d_change_sign}{d_change}</b></span><span>最高: <b style="color:#ef5350">{d_max}</b></span><span>最低: <b style="color:#26a69a">{d_min}</b></span><span></span></div>'
        return {
            "distance_list": distance_list,
            "stats_html": stats_html,
            "legend_html": "",
        }

    def _build_ap_chart_asset_data(self, asset_timeline, current_view):
        """解析资产时间线，构造对应统计和图例。"""
        asset_raw_points = []
        if asset_timeline and current_view in ("line", "detail"):
            for pt in asset_timeline:
                ts_raw = pt.get("ts", "")
                if ts_raw:
                    try:
                        va_dt = datetime.fromisoformat(ts_raw)
                        asset_value = self._snapshot_float(pt, "asset")
                    except (TypeError, ValueError):
                        continue
                    if asset_value is None:
                        continue
                    asset_raw_points.append({"dt": va_dt, "asset": asset_value})

        asset_list = []
        asset_ts_list = []
        for asset_point in sorted(asset_raw_points, key=lambda point: point["dt"]):
            asset_list.append(asset_point["asset"])
            asset_ts_list.append(int(asset_point["dt"].timestamp() * 1000))

        stats_html = ""
        if asset_list:
            valid_asset = [v for v in asset_list if v is not None]
            if valid_asset:
                a_cur = valid_asset[-1]
                a_change = (
                    valid_asset[-1] - valid_asset[0] if len(valid_asset) >= 2 else 0
                )
                a_change_color = "#ef5350" if a_change >= 0 else "#26a69a"
                a_change_sign = "+" if a_change >= 0 else ""
                a_max = max(valid_asset)
                a_min = min(valid_asset)

                stats_html += f'<div style="display:grid; grid-template-columns:150px 100px 90px 90px 90px; gap:8px; margin-bottom:2px; font-size:12px; color:#aaa;"><span>资产: <b style="color:#22d3ee">{a_cur:.1f}</b></span><span>变化: <b style="color:{a_change_color}">{a_change_sign}{a_change:.1f}</b></span><span>最高: <b style="color:#ef5350">{a_max:.1f}</b></span><span>最低: <b style="color:#26a69a">{a_min:.1f}</b></span><span></span></div>'
        return {
            "asset_list": asset_list,
            "asset_ts_list": asset_ts_list,
            "stats_html": stats_html,
            "legend_html": "",
        }

    @staticmethod
    def _combine_ap_chart_auxiliary_data(coins_data, distance_data, asset_data):
        """按模板约定组合辅助序列、摘要 HTML 与图例。"""
        return {
            "yellow_coins_list": coins_data["yellow_coins_list"],
            "purple_coins_list": coins_data["purple_coins_list"],
            "distance_list": distance_data["distance_list"],
            "asset_list": asset_data["asset_list"],
            "asset_ts_list": asset_data["asset_ts_list"],
            "coins_stats_html": (
                coins_data["stats_html"]
                + distance_data["stats_html"]
                + asset_data["stats_html"]
            ),
            "coins_legend_html": (
                coins_data["legend_html"]
                + distance_data["legend_html"]
                + asset_data["legend_html"]
            ),
        }

    @staticmethod
    def _snapshot_int(point, key):
        """将快照中的可选数值转换为整数，无效值保持为空。"""
        value = point.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _snapshot_float(point, key):
        """将快照中的可选数值转换为浮点数。"""
        value = point.get(key)
        if value is None:
            return None
        return float(value)

    def _render_ap_chart_content(self, chart_data, auxiliary_data):
        """将已装配的数据填充到 HTML，并把结构化的图表载荷交给前端渲染。

        不再以字符串注入 JS 模板，而是把纯数据 JSON 放在
        ``window.__apChartPayload``，由 ``webapp/ap_chart_echarts.js`` 读取。
        """
        current_view = chart_data["current_view"]
        chart_id = f"ap_cv_{id(self)}"

        template_fields = dict(
            chart_id=chart_id,
            view_title=chart_data["view_title"],
            ap_cur=chart_data["ap_cur"],
            change_color=chart_data["change_color"],
            change_sign=chart_data["change_sign"],
            ap_change=chart_data["ap_change"],
            ap_max=chart_data["ap_max"],
            ap_min=chart_data["ap_min"],
            ap_avg=chart_data["ap_avg"],
            data_points_text=chart_data["data_points_text"],
            coins_stats_html=auxiliary_data["coins_stats_html"],
        )
        html_tpl = read_webapp_template("ap_chart_panel.html")
        with use_scope("ap_chart", clear=True):
            put_html(html_tpl.format(**template_fields))
            render_toolbar = getattr(self, "_render_ap_chart_toolbar", None)
            if callable(render_toolbar):
                render_toolbar(current_view, chart_id)

        payload = {
            "view": current_view,
            "chartType": "candlestick" if current_view in ("day", "month") else "line",
            "labels": chart_data["labels"],
            "opens": chart_data["opens"],
            "highs": chart_data["highs"],
            "lows": chart_data["lows"],
            "closes": chart_data["closes"],
            "counts": chart_data["counts"],
            "ap": chart_data["ap_list"],
            "apTs": chart_data["ap_ts"],
            "sources": chart_data["detail_sources"],
            "purpleCoins": auxiliary_data["purple_coins_list"],
            "yellowCoins": auxiliary_data["yellow_coins_list"],
            "asset": auxiliary_data["asset_list"],
            "assetTs": auxiliary_data["asset_ts_list"],
            "distance": auxiliary_data["distance_list"],
            "avg": chart_data["ap_avg"],
            "isDetailMode": chart_data["is_detail_mode"],
        }
        self._inject_chart_scripts(
            chart_id=chart_id,
            payload=payload,
            render_fn="__renderApChart",
            render_script=read_webapp_template("ap_chart_echarts.js"),
        )
