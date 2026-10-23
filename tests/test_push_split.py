"""超长日报「尽量合并」分条推送 + PushPlus 频率排队的离线回归测试（不发 HTTP 请求）。

覆盖：
  - 栏目头 / 正文锚点解析（_section_title_text / _split_section_units）；
  - 顺序装箱（_pack_section_units）：整栏装箱、切栏续接、碎片保护、条数取最小；
  - 整页拆分（_split_html_for_push）：每条 ≤ 单条上限、外壳与页脚齐全、标签平衡、
    正文一个字不丢、横幅如实标注「承接上条（续）」「本条未完」；
  - PushPlus「1 分钟 N 次请求」排队（_push_rate_wait / _wait_push_rate_limit）；
  - PushPlus 默认一对多群组（2026-10-23）：群组编码取 PUSHPLUS_TOPIC，本地缺失时告警并
    回退一对一；Actions 工作流 Secret 缺省时兜底群组 oai.1；PUSHPLUS_MODE=one2one 可
    显式改回一对一直发自己；显式 topic 参数优先；
  - 微信推送标题（build_push_title）：[OCTOPUS] 关键词前缀、(强制) / (状态) 标记位置、
    时间戳永远在末尾、四条推送路径共用一个出口、分条 (i/N) 不挤掉推送时刻。
"""
import importlib.util
import io
import os
import re
import sys
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_push_split_under_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
              "meta", "param", "source", "track", "wbr", "rect", "line", "circle",
              "path", "polyline", "polygon", "ellipse"}
_TITLE_RE = re.compile(r"(<title>)(.*?)(</title>)", re.S)
_BANNER_RE = re.compile(r"<table[^>]*>.*?已尽量合并推送.*?</table>", re.S)
_SHELL = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
          '<meta name="octopus-theme" content="guizang"><title>测试日报</title>'
          '</head><body><table><tr><td>')          # 外层容器故意不闭合，由页脚闭合
_TAIL = "</td></tr></table></body></html>"


def _text(html):
    """去注释、去标签、去空白后的纯文本（用于「内容一个字不丢」比对）。"""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html))


class _BalanceChecker(HTMLParser):
    """检查 HTML 标签是否自闭合平衡（错配的标签记进 bad）。"""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.bad = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.bad.append(tag)


def _balanced(html):
    checker = _BalanceChecker()
    checker.feed(html)
    return checker.stack == [] and checker.bad == []


def _mk_unit(title, body_html, accent="行情速览"):
    """造一个 (栏目头, 栏目名, 正文) 单元：直接切真实渲染器（guizang 主题）的栏目。

    不能自己拼「栏目头 + 正文」——现行 guizang 版式里栏目头开的外层 div 是由正文末尾
    闭合的（``gz_section`` 的 head + content 合起来才是一个完整栏目），手拼出来的
    半截结构会让「标签平衡」类断言失去意义。
    """
    section = pipeline.gz_section(
        "01", "market", title, pipeline.gz_shell(body_html, pad="0 0 32px"))
    header, separator, content = section.partition(pipeline.SECTION_BODY_MARK)
    assert separator, "栏目渲染器必须带 <!--BODY--> 锚点"
    return header, title, content


def _section(num, title, body, accent="行情速览"):
    """按 guizang 主题造一个完整栏目（栏目头 + <!--BODY--> + 正文）。"""
    header, _, content = _mk_unit(title, body, accent=accent)
    return header + pipeline.SECTION_BODY_MARK + content


def _report(sections):
    body = pipeline.PART_BREAK_MARK + pipeline.PART_BREAK_MARK.join(sections)
    return _SHELL + body + "\n" + pipeline.DOC_FOOT_MARK + _TAIL


class SectionUnitTests(unittest.TestCase):
    """栏目头 / 正文锚点的解析。"""

    def test_guizang_section_title_is_extracted(self):
        head = pipeline.gz_section("01", "market", "行情速览", "正文").split(
            pipeline.SECTION_BODY_MARK)[0]
        self.assertEqual(pipeline._section_title_text(head), "行情速览")

    def test_pixel_section_title_is_extracted(self):
        head = pipeline._section("01", "行情速览", "港股名家频道", "正文").split(
            pipeline.SECTION_BODY_MARK)[0]
        self.assertEqual(pipeline._section_title_text(head), "港股名家频道")

    def test_long_title_is_shortened_for_banner(self):
        head = pipeline.gz_section("01", "market", "甲" * 60, "正文").split(
            pipeline.SECTION_BODY_MARK)[0]
        title = pipeline._section_title_text(head)
        self.assertTrue(title.endswith("…"))
        self.assertLessEqual(len(title), 29)

    def test_legacy_section_without_anchor_keeps_whole_html(self):
        units = pipeline._split_section_units(["<div>老版栏目</div>"])
        self.assertEqual(units, [("", "", "<div>老版栏目</div>")])

    def test_section_is_split_into_header_and_body(self):
        units = pipeline._split_section_units([_section("01", "行情速览", "<p>甲</p>")])
        header, title, content = units[0]
        self.assertEqual(title, "行情速览")
        # guizang 版式：栏目头表格化；正文段落另起表格，外层 div 在正文末闭合。
        self.assertTrue(header.endswith("</table>"))
        self.assertIn("</h2>", header)
        self.assertTrue(content.startswith("<table"))
        self.assertTrue(content.endswith("</div>"))
        self.assertNotIn(pipeline.SECTION_BODY_MARK, header + content)


class PackSectionUnitsTests(unittest.TestCase):
    """顺序装箱：条数取最小，但绝不切出碎片条。"""

    def test_whole_sections_share_one_part_when_they_fit(self):
        units = [_mk_unit("甲栏", "<p>" + "甲" * 300 + "</p>"),
                 _mk_unit("乙栏", "<p>" + "乙" * 300 + "</p>")]
        budget = sum(len(header + content) for header, _, content in units) + 10
        chunks, titles = pipeline._pack_section_units(units, budget)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(titles, [""])
        self.assertLessEqual(len(chunks[0]), budget)
        self.assertIn("甲栏", _text(chunks[0]))
        self.assertIn("乙栏", _text(chunks[0]))

    def test_section_is_cut_to_fill_current_part_and_continued(self):
        # 第一栏很小、第二栏很长：第二栏应被切开填满第一条，续片重开栏目头
        units = [_mk_unit("第一栏", "<p>" + "甲" * 400 + "</p>"),
                 _mk_unit("第二栏", "<p>" + "乙" * 6000 + "</p>")]
        budget = len(units[0][0] + units[0][2]) + 3000
        chunks, titles = pipeline._pack_section_units(units, budget, min_split=500)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(titles[0], "")
        self.assertEqual(titles[1], "第二栏")
        self.assertTrue(chunks[1].startswith(units[1][0]))
        for chunk in chunks[:-1]:
            self.assertLessEqual(len(chunk), budget)
            self.assertGreater(len(chunk), budget - 400)   # 每条都填满，不浪费额度
        self.assertEqual(_text("".join(chunks)).count("乙"), 6000)   # 一个字不丢

    def test_tiny_leftover_moves_whole_section_to_next_part(self):
        units = [_mk_unit("第一栏", "<p>" + "甲" * 400 + "</p>"),
                 _mk_unit("第二栏", "<p>" + "乙" * 400 + "</p>")]
        budget = len(units[0][0] + units[0][2]) + 200      # 剩余空间 < min_split
        chunks, titles = pipeline._pack_section_units(units, budget, min_split=1500)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(titles, ["", ""])
        self.assertEqual(_text(chunks[0]).count("乙"), 0)   # 不切出碎片条
        self.assertEqual(_text(chunks[1]).count("乙"), 400)

    def test_long_unbreakable_text_is_cut_at_text_boundary(self):
        # 一整段没有任何标签的长正文：退一步切在正文中间，仍能合并、且不丢字
        units = [_mk_unit("第一栏", "乙" * 9000)]
        chunks, titles = pipeline._pack_section_units(units, 4000, min_split=500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4000)
        self.assertEqual(_text("".join(chunks)).count("乙"), 9000)      # 一个字不丢
        self.assertGreaterEqual(_text("".join(chunks)).count("第一栏"), 1)  # 栏目头仍在

    def test_every_piece_is_tag_balanced(self):
        units = [_mk_unit("甲栏", "<table><tr><td>" + "甲" * 5000 + "</td></tr></table>"),
                 _mk_unit("乙栏", "<table><tr><td>" + "乙" * 5000 + "</td></tr></table>")]
        chunks, _ = pipeline._pack_section_units(units, 3000, min_split=500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(_balanced(chunk), chunk[:120])


class SplitHtmlForPushTests(unittest.TestCase):
    """整页拆分：合并到最少条数，同时保证每条都是完整、标签平衡、内容不丢的 HTML。"""

    def _split(self, html, limit, **kwargs):
        parts = pipeline._split_html_for_push(html, limit, "fake.html", **kwargs)
        self.assertIsNotNone(parts)
        return parts

    def _chunks(self, html, parts):
        """按拆分器自己的规则还原每条正文（去掉外壳、横幅、页脚）。"""
        first = html.find(pipeline.PART_BREAK_MARK)
        foot = html.find(pipeline.DOC_FOOT_MARK)
        shell = html[:first]
        tail = html[foot + len(pipeline.DOC_FOOT_MARK):]
        chunks = []
        for index, part in enumerate(parts, 1):
            head = _TITLE_RE.sub(
                lambda m: f"{m.group(1)}{m.group(2)}（第 {index}/{len(parts)} 条）{m.group(3)}",
                shell, count=1)
            self.assertTrue(part.startswith(head), "每条都要带完整刊头")
            self.assertTrue(part.endswith(tail), "每条都要带页脚与闭合标签")
            inner = part[len(head):len(part) - len(tail)]
            banner = _BANNER_RE.search(inner)
            self.assertIsNotNone(banner, "每条都要有条序横幅")
            chunks.append(inner[banner.end():])
        return chunks

    def test_parts_never_exceed_limit_and_keep_every_character(self):
        sections = [_section("00", "散户情绪因子", "<p>" + "甲" * 4000 + "</p>"),
                    _section("01", "行情速览", "<p>" + "乙" * 9000 + "</p>"),
                    _section("02", "全球头条", "<p>" + "丙" * 3000 + "</p>")]
        html = _report(sections)
        parts = self._split(html, 6000)
        for part in parts:
            self.assertLessEqual(len(part), 6000)
            self.assertTrue(_balanced(part))
        chunks = self._chunks(html, parts)
        merged = _text("".join(chunks))
        # 每个栏目名都要出现（续片重开栏目头时会出现多次，缺失则说明内容被丢了）
        for title in ("散户情绪因子", "行情速览", "全球头条"):
            self.assertIn(title, merged)
        # 正文一个字符不丢：三段正文的字符数完全一致
        original = _text(html[html.find(pipeline.PART_BREAK_MARK):
                              html.find(pipeline.DOC_FOOT_MARK)])
        for filler in "甲乙丙":
            self.assertEqual(merged.count(filler), original.count(filler))

    def test_every_part_but_the_last_is_filled_to_the_limit(self):
        # 三栏各 ~9000 字：必须切栏续接，而不是「一栏一条」白多推几条
        sections = [_section(f"0{i}", f"栏目{i}", "<p>" + "甲" * 9000 + "</p>")
                    for i in range(3)]
        html = _report(sections)
        parts = self._split(html, 22000)
        for part in parts[:-1]:
            self.assertGreater(len(part), 22000 * 0.9)

    def test_merging_uses_fewer_parts_than_whole_section_packing(self):
        # 同一条日报：允许栏目内续接时，条数必须比「整栏装箱」少（这正是「尽量合并」）
        sections = [_section(f"0{i}", f"栏目{i}", "<p>" + "甲" * 4000 + "</p>")
                    for i in range(3)]
        html = _report(sections)
        limit = int(len(sections[0]) * 1.8)      # 一条装得下 1 栏多一点，装不下 2 整栏
        merged = self._split(html, limit)
        with patch.object(pipeline, "PUSHPLUS_SPLIT_MIN_BODY", 10 ** 9):   # 只允许整栏装箱
            packed = self._split(html, limit)
        self.assertLess(len(merged), len(packed))
        for part in merged + packed:
            self.assertLessEqual(len(part), limit)

    def test_banners_tell_reader_where_the_section_continues(self):
        sections = [_section("00", "行情速览", "<p>" + "甲" * 6000 + "</p>"),
                    _section("01", "全球头条", "<p>" + "乙" * 6000 + "</p>")]
        html = _report(sections)
        parts = self._split(html, 4000)
        self.assertGreater(len(parts), 1)
        self.assertNotIn("承接上条", parts[0])
        self.assertIn("本条未完", parts[0])
        self.assertIn("承接上条「行情速览」（续）", parts[1])
        self.assertIn("承接上条", parts[-1])

    def test_legacy_report_without_body_anchor_still_merges(self):
        # 旧版日报没有 <!--BODY-->：续片不带栏目头，但同样按上限填满、内容不丢
        sections = ["<div>" + "旧" * 5000 + "</div>", "<div>" + "版" * 5000 + "</div>"]
        html = _report(sections)
        parts = self._split(html, 4000)
        for part in parts:
            self.assertLessEqual(len(part), 4000)
            self.assertTrue(_balanced(part))
        chunks = self._chunks(html, parts)
        self.assertEqual(_text("".join(chunks)), _text("".join(sections)))

    def test_report_without_anchors_returns_none(self):
        self.assertIsNone(pipeline._split_html_for_push("<html>" + "字" * 500 + "</html>", 100))

    def test_tail_cut_keeps_honest_banner_when_max_parts_exceeded(self):
        # 4 栏 × 3000 字正文 ≈ 1.35 万字 > 2 条 × 6000 字上限，必然触发收尾条
        sections = [_section(f"0{i}", f"栏目{i}", "<p>" + "甲" * 3000 + "</p>")
                    for i in range(4)]
        html = _report(sections)
        parts = self._split(html, 6000, max_parts=2)
        self.assertEqual(len(parts), 2)
        self.assertIn("已达单次推送条数上限", parts[-1])
        self.assertIn("完整日报", parts[-1])


class StyledDeliveryTests(unittest.TestCase):
    """推送的真实 HTML 不能悄悄退化为另一套白底纯文本风格。"""

    def test_dossier_color_protection_uses_dossier_palette(self):
        # 生成时已经使用档案深灰；推送端二次加固不应改成归藏的 #222。
        html = ('<meta name="octopus-theme" content="dossier">'
                '<div style="color:#4A4A4A">档案深灰</div>'
                '<div style="background:#F1F1F1">未设字色</div>')
        with patch.object(pipeline, "_push_one_message", return_value=True) as send:
            self.assertTrue(pipeline.push_to_wechat("上水日报", html, token="test-token"))
        sent = send.call_args.args[1]
        self.assertIn(f'color:{pipeline.D_GRAY}">档案深灰', sent)
        self.assertIn(f'background:{pipeline.D_PAPER};color:{pipeline.D_INK}">未设字色', sent)
        self.assertNotIn('color:#222', sent)
        # 浅灰画布 #F1F1F1 不能被灰字强制门禁误判成「浅灰文字」而改深
        self.assertIn(f'color:{pipeline.D_INK}"', sent)

    def test_dossier_stays_dossier_above_single_message_limit(self):
        masthead = pipeline._dossier_masthead("2026年10月4日 · 周日", "20261004", 2, 3,
                                               "2026-10-04 19:31:04")
        def section(n, text):
            body = f'<div style="color:{pipeline.D_INK};">{text}</div>'
            return pipeline.dossier_section(n, "MARKET", "市场简报", body)

        html = pipeline._dossier_html_frame(
            masthead, section("00", "甲" * 4300),
            pipeline.PART_BREAK_MARK + section("01", "乙" * 4300),
            "仅供参考", "20261004", "2026-10-04 19:31:04", 2, 3)
        limit = 9000
        self.assertGreater(len(html), limit)
        with (patch.object(pipeline, "PUSHPLUS_MAX_CONTENT_CHARS", limit),
              patch.object(pipeline, "_push_html_parts", return_value=True) as send_parts,
              patch.object(pipeline, "_push_one_message") as send_one,
              patch.object(pipeline, "_compact_html_for_push",
                           side_effect=AssertionError("风格丢失"))):
            self.assertTrue(pipeline.push_to_wechat("上水日报", html, token="test-token"))
        send_one.assert_not_called()
        sent = send_parts.call_args.args[1]
        self.assertGreater(len(sent), 1)
        for part in sent:
            self.assertLessEqual(len(part), limit)
            self.assertTrue(_balanced(part))
            self.assertIn('name="octopus-theme" content="dossier"', part)
            self.assertIn("AKTE", part)
            self.assertIn(pipeline.D_TAB, part)  # 分条横幅也应与档案纸风格一致
            self.assertNotIn("推送精简排版", part)
        self.assertEqual("".join(sent).count("甲"), 4300)
        self.assertEqual("".join(sent).count("乙"), 4300)


class PushDeliveryModeTests(unittest.TestCase):
    """推送路由（2026-10-23 按用户要求由一对一改为一对多）。

    默认一对多群组：群组编码从 PUSHPLUS_TOPIC 读取；未配置时打印明确告警并回退一对一；
    PUSHPLUS_MODE=one2one 可显式改回一对一直发自己；显式 topic 参数优先级最高。
    """

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"code": 200, "msg": "success"}

    def _send(self, **kwargs):
        with (patch.object(pipeline.requests, "post", return_value=self._Response(), create=True) as post,
              patch.object(pipeline, "_wait_push_rate_limit")):
            self.assertTrue(pipeline._push_one_message(
                "测试日报", "<p>测试</p>", token="test-token", **kwargs))
        return post.call_args.kwargs["json"]

    def test_default_mode_is_one_to_many(self):
        """默认即一对多（不再需要手动打开）；缺省常量就是 one2many。"""
        self.assertEqual(pipeline.PUSH_MODE_ONE2MANY, "one2many")
        self.assertEqual(pipeline.PUSH_MODE_ONE2ONE, "one2one")
        self.assertEqual(pipeline.PUSH_MODES, ("one2many", "one2one"))
        mode, topic = pipeline.resolve_push_route(None, mode="one2many")
        self.assertIn(mode, pipeline.PUSH_MODES)

    def test_group_code_from_env_routes_to_one_to_many(self):
        """PUSHPLUS_TOPIC 配好 → 发到一对多群组，payload 带 topic。"""
        with patch.object(pipeline, "PUSHPLUS_MODE", "one2many"), \
                patch.object(pipeline, "PUSHPLUS_TOPIC", "grp.2"):
            mode, topic = pipeline.resolve_push_route(None)
            payload = self._send()
        self.assertEqual((mode, topic), ("one2many", "grp.2"))
        self.assertEqual(payload["topic"], "grp.2")

    def test_missing_group_code_warns_and_falls_back(self):
        """一对多但没配群组编码 → 明确告警 + 回退一对一（不静默、不写死编码）。"""
        buf = io.StringIO()
        with patch.object(pipeline, "PUSHPLUS_MODE", "one2many"), \
                patch.object(pipeline, "PUSHPLUS_TOPIC", ""), redirect_stdout(buf):
            mode, topic = pipeline.resolve_push_route(None)
            payload = self._send()
            text = buf.getvalue()
        self.assertEqual((mode, topic), ("one2one", ""))
        self.assertNotIn("topic", payload)
        self.assertIn("PUSHPLUS_TOPIC", text)
        self.assertIn("回退一对一", text)

    def test_one2one_mode_ignores_env_group(self):
        """显式 PUSHPLUS_MODE=one2one → 一对一；即使环境里有群组编码也不携带。"""
        with patch.object(pipeline, "PUSHPLUS_MODE", "one2one"), \
                patch.object(pipeline, "PUSHPLUS_TOPIC", "grp.2"):
            mode, topic = pipeline.resolve_push_route(None)
            payload = self._send()
        self.assertEqual((mode, topic), ("one2one", ""))
        self.assertNotIn("topic", payload)

    def test_unknown_mode_warns_and_uses_one_to_many(self):
        """配置写错（未知模式）→ 告警并按默认一对多处理，不悄悄退回一对一。"""
        buf = io.StringIO()
        with patch.object(pipeline, "PUSHPLUS_MODE", "one2much"), \
                patch.object(pipeline, "PUSHPLUS_TOPIC", "grp.2"), redirect_stdout(buf):
            mode, topic = pipeline.resolve_push_route(None)
        self.assertEqual((mode, topic), ("one2many", "grp.2"))
        self.assertIn("PUSHPLUS_MODE", buf.getvalue())

    def test_push_log_reports_route(self):
        """推送日志写清本次走哪条路由（一对一 / 一对多群组 <编码>）。"""
        self.assertEqual(pipeline.push_route_text("one2many", "grp.2"), "一对多群组 grp.2")
        self.assertEqual(pipeline.push_route_text("one2one", ""), "一对一")

    def test_explicit_topic_enables_one_to_many_group(self):
        with patch.object(pipeline, "PUSHPLUS_TOPIC", ""):
            payload = self._send(topic="oai.1")
        self.assertEqual(payload["topic"], "oai.1")

    def test_empty_topic_override_falls_back_to_one_to_one(self):
        with patch.object(pipeline, "PUSHPLUS_TOPIC", "oai.1"):
            payload = self._send(topic="")
        self.assertNotIn("topic", payload)


class PushWorkflowTopicDefaultTests(unittest.TestCase):
    """Actions 工作流里的群组编码兜底值（2026-10-23 用户指定群组 oai.1）。

    群组编码本身仍不写进 Python 代码：Secret `PUSHPLUS_TOPIC` 优先，Secret 没配时由工作流
    兜底成 `oai.1`；因此「配了 Secret 改群」和「没配 Secret 用仓库默认群」都不用改代码。
    """

    WORKFLOWS = (".github/workflows/octopus-daily.yml",
                 ".github/workflows/manual.yml",
                 "output/manual_push_workflow.yml.example")

    def test_topic_falls_back_to_repo_group(self):
        repo_root = Path(__file__).parents[1]
        for relpath in self.WORKFLOWS:
            with self.subTest(workflow=relpath):
                text = (repo_root / relpath).read_text(encoding="utf-8")
                self.assertIn("PUSHPLUS_TOPIC: ${{ secrets.PUSHPLUS_TOPIC || 'oai.1' }}", text)

    def test_mode_defaults_to_one_to_many(self):
        repo_root = Path(__file__).parents[1]
        for relpath in self.WORKFLOWS:
            with self.subTest(workflow=relpath):
                text = (repo_root / relpath).read_text(encoding="utf-8")
                self.assertIn("PUSHPLUS_MODE: ${{ vars.PUSHPLUS_MODE || 'one2many' }}", text)

    def test_group_code_not_hardcoded_in_python(self):
        """兜底值只在工作流里；pipeline / push 源码不出现具体群组编码。"""
        repo_root = Path(__file__).parents[1]
        for relpath in ("output/pipeline.py", "output/push.py"):
            with self.subTest(source=relpath):
                text = (repo_root / relpath).read_text(encoding="utf-8")
                self.assertNotIn("PUSHPLUS_TOPIC = \"oai.1\"", text)
                self.assertNotRegex(text, r"PUSHPLUS_TOPIC[^\n]*=\s*os\.environ\.get\([^\n]*oai\.1")


class PushRateLimitTests(unittest.TestCase):
    """PushPlus 频率限制排队：窗口内请求数达上限时先等待，再放行。"""

    class _Clock:
        def __init__(self):
            self.now = 0.0
            self.slept = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.now += seconds

    def setUp(self):
        pipeline._PUSH_REQUEST_TIMES.clear()

    def tearDown(self):
        pipeline._PUSH_REQUEST_TIMES.clear()

    def test_wait_is_zero_below_limit(self):
        self.assertEqual(pipeline._push_rate_wait([0.0, 1.0], 2.0, window=60, limit=5), 0.0)

    def test_wait_until_oldest_request_leaves_the_window(self):
        history = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(
            pipeline._push_rate_wait(history, 10.0, window=60, limit=5), 50.0)

    def test_sixth_request_waits_for_the_window(self):
        clock = self._Clock()
        with patch.object(pipeline.time, "monotonic", clock.monotonic), \
                patch.object(pipeline.time, "sleep", clock.sleep), \
                patch.object(pipeline, "PUSHPLUS_RATE_WINDOW", 60.0), \
                patch.object(pipeline, "PUSHPLUS_RATE_MAX", 5):
            for _ in range(6):
                pipeline._wait_push_rate_limit()
        self.assertEqual(len(clock.slept), 1)
        self.assertAlmostEqual(clock.slept[0], 60.0, places=6)
        # 窗口滑过后早期请求已被清理，只剩最新一次请求在队列里
        self.assertEqual(len(pipeline._PUSH_REQUEST_TIMES), 1)

    def test_pacing_can_be_disabled(self):
        clock = self._Clock()
        with patch.object(pipeline.time, "monotonic", clock.monotonic), \
                patch.object(pipeline.time, "sleep", clock.sleep), \
                patch.object(pipeline, "PUSHPLUS_RATE_MAX", 0):
            for _ in range(20):
                pipeline._wait_push_rate_limit()
        self.assertEqual(clock.slept, [])


class PushTitleTests(unittest.TestCase):
    """微信推送标题（2026-10-13 改版）：[OCTOPUS] 前缀 + 刊头 + 「- 日期时间」。

    标题是用户在微信消息列表里唯一能看到的字段，格式必须稳定：
      - 前缀是 [OCTOPUS] 关键词，不再是 emoji（emoji 会被部分客户端与转发链路裁掉）；
      - 日期时间永远在末尾，(强制) / (状态) 紧跟刊头，分条 (i/N) 接在时间之后；
      - 只改推送标题：刊头与页面 <title> 用的 REPORT_TITLE 不带 [OCTOPUS]；
      - 「日报未推送提醒」「日报推送失败提醒」两条告警仍带 🐙，不混进关键词。
    """

    STAMP = datetime(2026, 10, 13, 23, 42, tzinfo=pipeline.CST)

    def test_prefix_is_the_octopus_keyword(self):
        self.assertEqual(pipeline.PUSH_TITLE_PREFIX, "[OCTOPUS] 章鱼 AI · 上水日报")
        self.assertNotIn("🐙", pipeline.PUSH_TITLE_PREFIX)

    def test_time_format_constant_is_the_one_used(self):
        self.assertEqual(pipeline.PUSH_TITLE_TIME_FMT, "%m/%d %H:%M")

    def test_title_layout(self):
        self.assertEqual(pipeline.build_push_title(when=self.STAMP),
                         "[OCTOPUS] 章鱼 AI · 上水日报 - 10/13 23:42")

    def test_mode_marker_sits_before_the_timestamp(self):
        for mode in ("(强制)", "(状态)"):
            title = pipeline.build_push_title(mode, when=self.STAMP)
            self.assertEqual(title, f"[OCTOPUS] 章鱼 AI · 上水日报{mode} - 10/13 23:42")
            self.assertTrue(title.endswith("- 10/13 23:42"), title)

    def test_default_when_uses_beijing_now(self):
        """when 留空取北京时间当前时刻：整体格式仍是「前缀 - MM/DD HH:MM」。"""
        title = pipeline.build_push_title()
        self.assertRegex(title, re.escape(pipeline.PUSH_TITLE_PREFIX) + r" - \d{2}/\d{2} \d{2}:\d{2}$")

    def test_page_title_keeps_the_plain_name(self):
        """只改推送标题：刊头与页面 <title> 用的 REPORT_TITLE 不带 [OCTOPUS]。"""
        self.assertEqual(pipeline.REPORT_TITLE, "章鱼 AI · 上水日报")
        self.assertNotIn("[OCTOPUS]", pipeline.REPORT_TITLE)

    def test_all_push_paths_share_one_builder(self):
        """四条推送路径（--push-only / 常规 / 强制 / 状态）都走 build_push_title，
        不再各自拼 PUSH_TITLE_PREFIX，避免哪天只改了一处、标题分叉。"""
        src = Path(pipeline.__file__).read_text(encoding="utf-8")
        call_sites = [line for line in src.splitlines()
                      if line.strip().startswith("title = build_push_title(")]
        self.assertEqual(len(call_sites), 4, f"推送路径数变了：{call_sites}")
        stray = [line for line in src.splitlines()
                 if re.search(r"^\s*title\s*=.*PUSH_TITLE_PREFIX", line)]
        self.assertEqual(stray, [], "推送标题必须由 build_push_title 统一拼装")

    def test_alert_titles_stay_emoji_and_bypass_the_builder(self):
        """两条纯文本告警是提醒而非日报本体：标题仍带 🐙，不带 [OCTOPUS] 关键词。"""
        src = Path(pipeline.__file__).read_text(encoding="utf-8")
        for name in ("日报未推送提醒", "日报推送失败提醒"):
            lines = [line for line in src.splitlines()
                     if name in line and line.strip().startswith("title = ")]
            self.assertTrue(lines, f"找不到 {name} 的标题拼装行")
            for line in lines:
                self.assertIn("🐙", line)
                self.assertNotIn("[OCTOPUS]", line)

    def test_multipart_suffix_follows_the_timestamp(self):
        """超长分条：每条标题为「… - MM/DD HH:MM (i/N)」，推送时刻不被 (i/N) 挤掉。"""
        html = _report([_section("01", "行情速览", "<p>" + "甲" * 12000 + "</p>"),
                        _section("02", "全球头条", "<p>" + "乙" * 12000 + "</p>")])
        sent = []
        title = pipeline.build_push_title(when=self.STAMP)
        with (patch.object(pipeline, "PUSHPLUS_MAX_CONTENT_CHARS", 10000),
              patch.object(pipeline, "PUSHPLUS_MULTIPART", True),
              patch.object(pipeline, "PUSHPLUS_PART_DELAY", 0),
              patch.object(pipeline, "_push_one_message",
                           lambda t, c, **kw: sent.append(t) or True)):
            self.assertTrue(pipeline.push_to_wechat(title, html, token="test-token",
                                                    report_name="daily_report_test.html"))
        self.assertGreater(len(sent), 1)
        for index, sent_title in enumerate(sent, 1):
            self.assertTrue(sent_title.startswith(title), sent_title)
            self.assertIn("- 10/13 23:42", sent_title)
            self.assertTrue(sent_title.endswith(f"({index}/{len(sent)})"), sent_title)


if __name__ == "__main__":
    unittest.main()
