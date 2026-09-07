import unittest

from module.webui.app_shell import branch_is_unstable, watermark_should_show


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

        files = sorted(glob.glob("config/deploy.template*.yaml")) + ["deploy/template"]
        self.assertTrue(files, "未找到部署模板")
        for file in files:
            config = poor_yaml_read(file)
            self.assertIs(
                config.get("ShowUnverifiedWatermark"), True, f"{file} 缺少开关或默认值不为 true"
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


if __name__ == "__main__":
    unittest.main()
