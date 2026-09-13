import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.webui.app_shell import (
    AppShellMixin,
    BRANCH_WATERMARK_MAX_MESSAGE_LEN,
    BRANCH_WATERMARK_NOTICE,
    BRANCH_WATERMARK_NOTICE_EN,
    BRANCH_WATERMARK_UNKNOWN_BRANCH,
    branch_is_unstable,
    branch_needs_watermark,
    branch_watermark_disabled,
    build_branch_watermark_lines,
    watermark_should_show,
    resolve_watermark_branch,
)


class TestBranchIsUnstable(unittest.TestCase):
    """验证稳定/非稳定分支判定，决定是否注入未验证版本水印。"""

    def test_stable_branches(self):
        for branch in ["master", "main"]:
            self.assertFalse(branch_is_unstable(branch), branch)

    def test_unstable_branches(self):
        for branch in ["dev", "app", "v2020.07.15", "feature/new"]:
            self.assertTrue(branch_is_unstable(branch), branch)

    def test_case_and_whitespace(self):
        self.assertFalse(branch_is_unstable("Master"))
        self.assertFalse(branch_is_unstable("  main  "))
        self.assertTrue(branch_is_unstable("DEV"))

    def test_empty_and_none_fallback_to_stable(self):
        # 空值与 None 回退为稳定，避免配置缺失时误触发水印。
        self.assertFalse(branch_is_unstable(None))
        self.assertFalse(branch_is_unstable(""))
        self.assertFalse(branch_is_unstable("   "))


class TestWatermarkShouldShow(unittest.TestCase):
    """验证部署开关 ShowUnverifiedWatermark 与分支判定的组合结果。"""

    def test_disabled_switch_suppresses_all_branches(self):
        # 开关关闭时，任何分支都不显示水印。
        for branch in ["dev", "app", "feature/new", "master", None, ""]:
            self.assertFalse(watermark_should_show(branch, False), branch)

    def test_enabled_switch_follows_branch(self):
        self.assertTrue(watermark_should_show("dev", True))
        self.assertTrue(watermark_should_show("app", True))
        self.assertFalse(watermark_should_show("master", True))
        self.assertFalse(watermark_should_show("main", True))

    def test_default_switch_is_enabled(self):
        # 省略开关参数时保持上游行为，非稳定分支仍然提示。
        self.assertTrue(watermark_should_show("dev"))
        self.assertFalse(watermark_should_show("master"))

    def test_falsy_switch_values_suppress(self):
        # 配置文件可能解析出 None 或 0，同样视为关闭。
        for value in [None, 0, ""]:
            self.assertFalse(watermark_should_show("dev", value), repr(value))


class TestDeployTemplateHasSwitch(unittest.TestCase):
    """确保所有部署模板都带上开关，避免升级后配置缺项回退默认值。"""

    def test_all_templates_declare_switch(self):
        import glob

        from deploy.utils import poor_yaml_read

        # deploy/Windows/template.yaml 是旧版 Windows 安装器模板：无可用 ADB 设备时
        # connection.py 会实例化 EmulatorManager，其 DeployConfig.read() 以该模板为
        # 骨架重写 config/deploy.yaml。poor_yaml_write() 只替换模板中已存在的键，
        # 模板缺项会被整条丢弃，用户关掉的开关将被静默恢复为默认值。
        files = (
            sorted(glob.glob("config/deploy.template*.yaml"))
            + ["deploy/template", "deploy/Windows/template.yaml"]
        )
        self.assertTrue(files, "未找到部署模板")
        for file in files:
            config = poor_yaml_read(file)
            self.assertIs(
                config.get("ShowUnverifiedWatermark"), True, f"{file} 缺少开关或默认值不为 true"
            )

    def test_both_config_models_declare_switch(self):
        # 主部署模型与旧版 Windows 安装器模型各自独立，缺一个都会导致开关读不回来。
        from deploy.config import ConfigModel
        from deploy.Windows.config import ConfigModel as WindowsConfigModel

        for model in [ConfigModel, WindowsConfigModel]:
            self.assertIs(
                getattr(model, "ShowUnverifiedWatermark", None),
                True,
                f"{model.__module__}.ConfigModel 缺少开关或默认值不为 true",
            )

    def test_legacy_windows_rewrite_preserves_user_choice(self):
        # 回归测试：以旧版 Windows 模板为骨架重写时，用户设的 false 必须留存。
        import tempfile
        from pathlib import Path

        from deploy.utils import poor_yaml_read, poor_yaml_write

        source = Path("config/deploy.template.yaml").read_text(encoding="utf-8")
        self.assertIn("ShowUnverifiedWatermark: true", source)
        disabled = source.replace(
            "ShowUnverifiedWatermark: true", "ShowUnverifiedWatermark: false"
        )

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "deploy.yaml"
            target.write_text(disabled, encoding="utf-8", newline="")
            config = poor_yaml_read(str(target))
            self.assertIs(config.get("ShowUnverifiedWatermark"), False)

            poor_yaml_write(
                config, str(target), template_file="deploy/Windows/template.yaml"
            )

            rewritten = poor_yaml_read(str(target))
            self.assertIn(
                "ShowUnverifiedWatermark",
                rewritten,
                "重写后开关被整条丢弃，用户设置将回退默认值",
            )
            self.assertIs(
                rewritten.get("ShowUnverifiedWatermark"),
                False,
                "重写后用户关闭的开关被恢复为 true",
            )


class TestDeploySettingExposesSwitch(unittest.TestCase):
    """确保开关出现在 WebUI 部署设置表单中，用户可在界面直接关闭水印。"""

    def test_switch_is_registered_as_bool_field(self):
        from module.webui.deploy_settings import DEPLOY_FIELDS

        field = DEPLOY_FIELDS.get("ShowUnverifiedWatermark")
        self.assertIsNotNone(field, "部署设置未注册 ShowUnverifiedWatermark")
        self.assertEqual(field.kind, "bool", "开关必须是 bool 才能渲染成开关控件")

    def test_switch_belongs_to_webui_group(self):
        # 放在 WebUI 分组，与主题、DPI 缩放等界面项同处一屏。
        from module.webui.deploy_settings import DEPLOY_GROUPS

        groups = dict(DEPLOY_GROUPS)
        keys = [field.key for field in groups["Webui"]]
        self.assertIn("ShowUnverifiedWatermark", keys)

    def test_switch_parses_bool_and_rejects_others(self):
        from module.webui.deploy_settings import DEPLOY_FIELDS, _parse_value

        field = DEPLOY_FIELDS["ShowUnverifiedWatermark"]
        self.assertIs(_parse_value(field, True), True)
        self.assertIs(_parse_value(field, False), False)
        for bad in ["true", 1, None]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                _parse_value(field, bad)

    def test_all_languages_translate_switch(self):
        # 生成器只写入 key 路径占位，必须人工翻译后才算完成。
        import json

        for lang in ["zh-CN", "zh-TW", "en-US", "ja-JP", "zh-MIAO"]:
            with open(f"module/config/i18n/{lang}.json", encoding="utf-8") as f:
                section = json.load(f)["Gui"]["DeploySetting"]
            for key in ["ShowUnverifiedWatermark", "ShowUnverifiedWatermarkHelp"]:
                value = section.get(key)
                self.assertTrue(value, f"{lang} 缺少 {key}")
                self.assertNotEqual(
                    value,
                    f"Gui.DeploySetting.{key}",
                    f"{lang} 的 {key} 仍是未翻译的 key 占位",
                )


def _texts(lines):
    return [line["text"] for line in lines]


class TestBuildBranchWatermarkLines(unittest.TestCase):
    """验证水印文案包含中英提醒、分支名、版本哈希与提交信息，标签使用 ASCII。"""

    COMMIT = ("a1b2c3d", "Neko", "2026-09-13 16:00:00 +0800", "Fix login loop")

    def test_with_commit(self):
        lines = build_branch_watermark_lines("dev", self.COMMIT)
        texts = _texts(lines)
        # 中英提醒各占一行且位于最前，中文为主、英文为副
        self.assertEqual(lines[0]["text"], BRANCH_WATERMARK_NOTICE)
        self.assertEqual(lines[0]["kind"], "title")
        self.assertEqual(lines[1]["text"], BRANCH_WATERMARK_NOTICE_EN)
        self.assertEqual(lines[1]["kind"], "title-en")
        self.assertEqual(len(lines), 5)
        self.assertIn("Ver.dev.a1b2c3d", texts)
        self.assertIn("Branche is:dev", texts)
        self.assertIn("Fix login loop", texts)
        # 元信息都应标记为 meta，便于 CSS 用小字号淡化。
        for line in lines[2:]:
            self.assertEqual(line["kind"], "meta")

    def test_both_notices_are_single_line(self):
        # 中英提醒各自合并为一行，不再拆成标题 + 页脚两句。
        for notice in (BRANCH_WATERMARK_NOTICE, BRANCH_WATERMARK_NOTICE_EN):
            self.assertNotIn("\n", notice)
        self.assertIn("您正在使用未经验证的版本", BRANCH_WATERMARK_NOTICE)
        self.assertIn("可能存在未知问题", BRANCH_WATERMARK_NOTICE)
        self.assertIn("unverified", BRANCH_WATERMARK_NOTICE_EN)

    def test_notice_en_is_pure_ascii(self):
        self.assertTrue(BRANCH_WATERMARK_NOTICE_EN.isascii())

    def test_no_chinese_labels_in_meta(self):
        for line in build_branch_watermark_lines("dev", self.COMMIT)[2:]:
            self.assertFalse(
                any("\u4e00" <= ch <= "\u9fff" for ch in line["text"]),
                line["text"],
            )

    def test_without_commit_falls_back_to_unknown_version(self):
        for commit in (None, (), (None, None, None, None)):
            with self.subTest(commit=commit):
                lines = build_branch_watermark_lines("app", commit)
                texts = _texts(lines)
                self.assertIn("Ver.app.unknown", texts)
                self.assertIn("Branche is:app", texts)
                # 中英提醒 + 版本 + 分支，无提交行
                self.assertEqual(len(lines), 4)

    def test_empty_branch_drops_branch_segments(self):
        texts = _texts(build_branch_watermark_lines("", self.COMMIT))
        self.assertIn("Ver.a1b2c3d", texts)
        self.assertFalse(any(t.startswith("Branche is:") for t in texts))

    def test_multiline_message_is_flattened_and_clipped(self):
        message = "line one\nline two " + "x" * 100
        lines = build_branch_watermark_lines("dev", ("sha1", "a", "t", message))
        # 提交内容裸写，无前缀，是最后一行
        subject = lines[-1]["text"]
        self.assertNotIn("\n", subject)
        self.assertTrue(subject.endswith("…"))
        self.assertEqual(len(subject), BRANCH_WATERMARK_MAX_MESSAGE_LEN)


class TestWatermarkInjection(unittest.TestCase):
    """验证合并后的注入入口同时遵守部署开关与版本信息展示。"""

    def test_disabled_switch_skips_version_lookup_and_injection(self):
        config = SimpleNamespace(
            Branch="dev", ShowUnverifiedWatermark=False, read=Mock()
        )
        with (
            patch("module.webui.app_shell.State.deploy_config", config),
            patch("module.webui.app_shell.updater.get_commit") as get_commit,
            patch("module.webui.app_shell.run_js") as run_js,
            patch.object(AppShellMixin, '_remove_branch_watermark') as remove,
        ):
            AppShellMixin()._inject_unverified_branch_watermark()

        get_commit.assert_not_called()
        run_js.assert_not_called()
        remove.assert_called_once_with()

    def test_enabled_switch_injects_version_metadata(self):
        config = SimpleNamespace(
            Branch="dev", ShowUnverifiedWatermark=True, read=Mock()
        )
        with (
            patch("module.webui.app_shell.State.deploy_config", config),
            patch(
                "module.webui.app_shell.updater.get_commit",
                return_value=TestBuildBranchWatermarkLines.COMMIT,
            ) as get_commit,
            patch("module.webui.app_shell.run_js") as run_js,
        ):
            AppShellMixin._inject_unverified_branch_watermark(None)

        get_commit.assert_called_once_with(short_sha1=True)
        run_js.assert_called_once()
        self.assertIn("Ver.dev.a1b2c3d", run_js.call_args.args[0])
        self.assertIn("Fix login loop", run_js.call_args.args[0])

    def test_failed_config_read_uses_git_branch(self):
        config = SimpleNamespace(read=Mock(side_effect=RuntimeError('unavailable')))
        with (
            patch("module.webui.app_shell.State.deploy_config", config),
            patch("module.webui.app_shell.detect_git_branch", return_value="dev"),
            patch("module.webui.app_shell.updater.get_commit", return_value=None),
            patch("module.webui.app_shell.run_js") as run_js,
        ):
            AppShellMixin()._inject_unverified_branch_watermark()

        self.assertIn("Ver.dev.unknown", run_js.call_args.args[0])


class TestBranchWatermarkDisabled(unittest.TestCase):
    """关闭水印开关的读取：默认关闭（即显示水印），只有显式配置才隐藏。

    配置缺失、属性不存在或读取异常都必须回退到「显示水印」，避免因为配置
    问题把提醒静默关掉——水印里的版本信息是定位问题的唯一线索。
    """

    def test_default_is_show(self):
        self.assertFalse(branch_watermark_disabled(None))
        self.assertFalse(branch_watermark_disabled(object()))
        self.assertFalse(branch_watermark_disabled(
            SimpleNamespace(DisableBranchWatermark=False)))

    def test_only_boolean_true_hides(self):
        """非布尔真值不算开启：格式写错的 deploy.yaml 不能静默关掉水印。"""
        for value in ("", "false", "False", "0", "no", "true", 0, 1, [], {}):
            with self.subTest(value=value):
                self.assertFalse(branch_watermark_disabled(
                    SimpleNamespace(DisableBranchWatermark=value)))

    def test_explicit_true_hides(self):
        self.assertTrue(branch_watermark_disabled(
            SimpleNamespace(DisableBranchWatermark=True)))

    def test_legacy_switch_remains_effective_with_upstream_default(self):
        for enabled, disabled, expected in (
            (True, False, False),
            (False, False, True),
            (True, True, True),
            (False, True, True),
        ):
            with self.subTest(enabled=enabled, disabled=disabled):
                config = SimpleNamespace(
                    ShowUnverifiedWatermark=enabled,
                    DisableBranchWatermark=disabled,
                )
                self.assertIs(branch_watermark_disabled(config), expected)

    def test_read_error_falls_back_to_show(self):
        class Broken:
            @property
            def DisableBranchWatermark(self):
                raise RuntimeError("boom")

        self.assertFalse(branch_watermark_disabled(Broken()))


class TestDeployModelsExposeSwitch(unittest.TestCase):
    """开关字段必须同时存在于各部署模型与模板。

    WebUI 用的是 module/webui/config.py 的子类（继承 deploy/config.py），
    Windows 启动器用的是 deploy/Windows/config.py 的独立模型，两者读写同一份
    config/deploy.yaml；字段缺失会让开关在对应平台上静默失效（读不到就恒为
    False，水印照样显示）。
    """

    def test_models_expose_field(self):
        from deploy.config import DeployConfig

        self.assertIs(DeployConfig.DisableBranchWatermark, False)

        from module.webui.config import DeployConfig as WebUIDeployConfig

        self.assertIs(WebUIDeployConfig.DisableBranchWatermark, False)

        try:
            from deploy.Windows.config import DeployConfig as WindowsDeployConfig
        except Exception as e:  # 非 Windows 环境可能无法导入
            self.skipTest(f"Windows 部署模型不可导入: {e}")
        self.assertIs(WindowsDeployConfig.DisableBranchWatermark, False)

    def test_deploy_templates_expose_field(self):
        import glob
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        patterns = [
            "config/deploy.template*.yaml",
            "deploy/template",
            "deploy/Windows/template.yaml",
        ]
        files = []
        for pattern in patterns:
            files.extend(glob.glob(os.path.join(root, pattern)))
        self.assertTrue(files, "未找到任何部署模板")
        for path in files:
            with self.subTest(template=os.path.basename(path)):
                with open(path, encoding="utf-8") as f:
                    self.assertIn("DisableBranchWatermark", f.read())


class TestWatermarkBranchResolution(unittest.TestCase):
    """分支名规范化与「是否需要水印」的判定。

    部署配置读取失败时不能把构建当成已验证的 master：先退回实际 git 分支，
    仍拿不到就按未知分支处理——水印是排查问题的诊断信息，宁可多显示，
    也不能因为一次读取失败被静默吞掉。
    """

    def test_resolve_keeps_real_branch(self):
        self.assertEqual(resolve_watermark_branch("dev"), "dev")
        self.assertEqual(resolve_watermark_branch(" feature/x "), "feature/x")

    def test_resolve_maps_empty_and_detached_head_to_unknown(self):
        for value in (None, "", "   ", "HEAD", " head "):
            with self.subTest(value=value):
                self.assertEqual(
                    resolve_watermark_branch(value),
                    BRANCH_WATERMARK_UNKNOWN_BRANCH)

    def test_stable_branches_need_no_watermark(self):
        for branch in ("master", "main", "Master", "  main  "):
            with self.subTest(branch=branch):
                self.assertFalse(branch_needs_watermark(branch))

    def test_unstable_branches_need_watermark(self):
        for branch in ("dev", "app", "v2020.07.15", "feature/x"):
            with self.subTest(branch=branch):
                self.assertTrue(branch_needs_watermark(branch))

    def test_unknown_branch_fails_safe_to_watermark(self):
        for branch in (None, "", "   ", "unknown", "UNKNOWN", "Unknown"):
            with self.subTest(branch=branch):
                self.assertTrue(branch_needs_watermark(branch))


if __name__ == "__main__":
    unittest.main()
