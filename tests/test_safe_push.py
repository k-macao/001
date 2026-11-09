#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📤 自动提交推送（tools/safe_push.sh + tools/merge_generated.py）回归测试 —— 全部离线。

对应事故（2026-10-02 ~ 10-04，三次 `! [rejected] HEAD -> main (fetch first)`）：
工作流在「检出那一刻的 main」上跑 2~15 分钟，期间 main 被别人推动（PR 合并 /
另一个工作流 / 重跑旧 run），最后一步 `git push origin HEAD` 被拒 → 作业标红，
且日报 HTML 与预测留痕 JSON 全部没进库。

本套钉死两件事：
  ① 合并策略（tools/merge_generated.py，纯函数，无 git 依赖）
     · 日报 HTML / 自校验库文件 → 整份以本次为准；
     · 追加型 JSON（news_history / sentiment_history / quant_history /
       hk7_forecast / weekly_forecast）→ 按键并集，两边条目都不丢；
     · 已结算（settled）的留痕不被未结算副本覆盖；本次的空值不擦掉远端实值；
     · 输出格式与各写入方逐字一致（否则每次运行都产生整文件无意义 diff）。
  ② 推送脚本（tools/safe_push.sh，用临时 bare 仓库 + 两个克隆真跑 git）
     · 远端前进（无关提交 / 同一文件冲突）后被拒 → 重放 → 推送成功；
     · 别人的改动（README、代码）绝不被回退；
     · 远端连动多次 → 多次重放直到成功；
     · 无新内容 → 不产生提交；远端已有相同内容 → 不产生重复提交；
     · 权限 / 保护分支 / 钩子拒绝 → 立即失败，不做无谓重试；
     · 收尾干净：不残留 rebase 状态、工作区干净、提交身份与信息不变。

不联网、不需要 GitHub 凭据；只依赖 git 与 python3（缺 git 时自动跳过 ②）。
运行：python3 tests/test_safe_push.py
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
OUTPUT_DIR = REPO_ROOT / "output"
for _p in (str(OUTPUT_DIR), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import merge_generated as mg                                  # noqa: E402

SAFE_PUSH = TOOLS_DIR / "safe_push.sh"
GIT = shutil.which("git")


# ============================================================
# ① 合并策略（纯函数）
# ============================================================
class TestMergePolicy(unittest.TestCase):
    """按文件类型路由到正确的合并策略。"""

    def test_policy_routing(self):
        self.assertEqual(mg.policy_for("output/news_history.json"), mg.POLICY_JOURNAL)
        self.assertEqual(mg.policy_for("output/hk7_forecast.json"), mg.POLICY_JOURNAL)
        self.assertEqual(mg.policy_for("output/weekly_forecast.json"), mg.POLICY_JOURNAL)
        self.assertEqual(mg.policy_for("output/sentiment_history.json"), mg.POLICY_LEDGER)
        self.assertEqual(mg.policy_for("output/quant_history.json"), mg.POLICY_LEDGER)
        self.assertEqual(mg.policy_for("output/push_state.json"), mg.POLICY_LEDGER)
        self.assertEqual(mg.policy_for("output/market_db/20261004.json"), mg.POLICY_LOCAL)
        self.assertEqual(mg.policy_for("output/latest.html"), mg.POLICY_LOCAL)
        self.assertEqual(mg.policy_for("README.md"), mg.POLICY_LOCAL)
        self.assertEqual(mg.policy_for("output/some_new_state.json"), mg.POLICY_DEEP)

    def test_policy_tolerates_path_noise(self):
        for path in ("./output/news_history.json", "output\\news_history.json"):
            self.assertEqual(mg.policy_for(path), mg.POLICY_JOURNAL)


class TestNewsHistoryMerge(unittest.TestCase):
    """新闻标题存档：并集 + 官方溯源不被降级。"""

    PATH = "output/news_history.json"

    def _item(self, title, date, **extra):
        base = {"title": title, "source": "华尔街见闻", "section": "全球头条",
                "ts": f"{date} 08:00", "date": date}
        base.update(extra)
        return base

    def test_union_keeps_both_sides_and_dedups(self):
        remote = {"version": 1, "items": [self._item("共有标题", "2026-10-04"),
                                          self._item("只有远端有", "2026-10-04")],
                  "updated_cst": "2026-10-04 09:47:00+0800"}
        local = {"version": 1, "items": [self._item("共有标题", "2026-10-04"),
                                         self._item("只有本次有", "2026-10-04")],
                 "updated_cst": "2026-10-04 09:50:00+0800"}
        merged = mg.merge_docs(self.PATH, remote, local)
        titles = [it["title"] for it in merged["items"]]
        self.assertEqual(sorted(titles), ["共有标题", "只有本次有", "只有远端有"])
        self.assertEqual(merged["updated_cst"], local["updated_cst"])   # 顶层以本次为准

    def test_official_source_not_downgraded_by_local(self):
        remote = {"version": 1, "items": [
            self._item("政策", "2026-10-04", official=True, source="中国政府网",
                       url="https://www.gov.cn/x")], "updated_cst": "x"}
        local = {"version": 1, "items": [self._item("政策", "2026-10-04")],
                 "updated_cst": "y"}
        merged = mg.merge_docs(self.PATH, remote, local)
        item = merged["items"][0]
        self.assertTrue(item["official"])
        self.assertEqual(item["url"], "https://www.gov.cn/x")
        self.assertEqual(item["source"], "中国政府网")

    def test_local_fills_missing_url(self):
        remote = {"version": 1, "items": [self._item("A", "2026-10-04")], "updated_cst": "x"}
        local = {"version": 1, "items": [self._item("A", "2026-10-04", url="https://e.cn/a")],
                 "updated_cst": "y"}
        merged = mg.merge_docs(self.PATH, remote, local)
        self.assertEqual(merged["items"][0]["url"], "https://e.cn/a")

    def test_append_order_is_remote_then_local_only(self):
        """新闻存档不重排：远端条目在前、本次新增在后（顺序对下游无意义，diff 最小）。"""
        remote = {"version": 1, "items": [self._item("远端", "2026-10-04", ts="2026-10-04 20:00")],
                  "updated_cst": "x"}
        local = {"version": 1, "items": [self._item("本次", "2026-10-04", ts="2026-10-04 06:00")],
                 "updated_cst": "y"}
        merged = mg.merge_docs(self.PATH, remote, local)
        self.assertEqual([it["title"] for it in merged["items"]], ["远端", "本次"])


class TestForecastJournalMerge(unittest.TestCase):
    """预测留痕（hk7 / weekly）：已结算者优先，远端条目不丢。"""

    def _entry(self, symbol="^HSI", base_date="2026-10-01", issued="2026-10-01 09:00:00+0800",
               **extra):
        entry = {"symbol": symbol, "base_date": base_date, "issued_cst": issued,
                 "settled": False, "p_up": 0.52}
        entry.update(extra)
        return entry

    def test_remote_settled_entry_survives_local_unsettled_copy(self):
        for path in ("output/hk7_forecast.json", "output/weekly_forecast.json"):
            with self.subTest(path=path):
                remote = {"version": 1,
                          "entries": [self._entry(settled=True, actual_chg=1.2, hit=True)]}
                local = {"version": 1, "entries": [self._entry()]}
                merged = mg.merge_docs(path, remote, local)
                self.assertEqual(len(merged["entries"]), 1)
                self.assertTrue(merged["entries"][0]["settled"])
                self.assertEqual(merged["entries"][0]["actual_chg"], 1.2)

    def test_union_of_different_symbols_and_dates(self):
        remote = {"version": 1, "entries": [self._entry(symbol="00700"),
                                            self._entry(base_date="2026-09-30")]}
        local = {"version": 1, "entries": [self._entry(symbol="09988")]}
        merged = mg.merge_docs("output/hk7_forecast.json", remote, local)
        keys = sorted((e["symbol"], e["base_date"]) for e in merged["entries"])
        self.assertEqual(keys, [("00700", "2026-10-01"), ("09988", "2026-10-01"),
                                ("^HSI", "2026-09-30")])

    def test_entries_sorted_chronologically(self):
        remote = {"version": 1, "entries": [self._entry(issued="2026-10-03 09:00:00+0800",
                                                        symbol="late")]}
        local = {"version": 1, "entries": [self._entry(issued="2026-10-01 09:00:00+0800",
                                                       symbol="early")]}
        merged = mg.merge_docs("output/weekly_forecast.json", remote, local)
        self.assertEqual([e["symbol"] for e in merged["entries"]], ["early", "late"])

    def test_local_wins_when_both_unsettled(self):
        remote = {"version": 1, "entries": [self._entry(p_up=0.40)]}
        local = {"version": 1, "entries": [self._entry(p_up=0.61)]}
        merged = mg.merge_docs("output/hk7_forecast.json", remote, local)
        self.assertEqual(merged["entries"][0]["p_up"], 0.61)


class TestLedgerMerge(unittest.TestCase):
    """情绪历史 / 量化历史：按键并集，结算结果不被擦掉。"""

    def test_sentiment_union_per_symbol_and_day(self):
        remote = {"version": 1, "stocks": {
            "港股:00700": {"market": "港股", "code": "00700", "name": "腾讯控股",
                          "days": {"20261003": {"pos": 3, "neu": 1, "neg": 0, "total": 4,
                                                "score": 0.75}}},
            "A股:300308": {"market": "A股", "code": "300308", "name": "中际旭创",
                          "days": {"20261003": {"pos": 1, "neu": 0, "neg": 0, "total": 1,
                                                "score": 1.0}}},
        }, "updated_cst": "2026-10-03 21:00:00+0800"}
        local = {"version": 1, "stocks": {
            "港股:00700": {"market": "港股", "code": "00700", "name": "腾讯控股",
                          "days": {"20261003": {"pos": 5, "neu": 2, "neg": 1, "total": 8,
                                                "score": 0.5},
                                  "20261004": {"pos": 2, "neu": 0, "neg": 0, "total": 2,
                                                "score": 1.0}}},
        }, "updated_cst": "2026-10-04 09:50:00+0800"}
        merged = mg.merge_docs("output/sentiment_history.json", remote, local)
        stocks = merged["stocks"]
        self.assertIn("A股:300308", stocks)                       # 远端独有 → 保住
        self.assertEqual(sorted(stocks["港股:00700"]["days"]), ["20261003", "20261004"])
        self.assertEqual(stocks["港股:00700"]["days"]["20261003"]["total"], 8)   # 同日本次为准
        self.assertEqual(merged["updated_cst"], local["updated_cst"])

    def test_quant_days_remote_settlement_preserved(self):
        remote = {"days": {
            "2026-10-02": {"headline_p": 0.52,
                           "result": {"date": "2026-10-02", "target": "2026-10-03",
                                      "marks": {"^HSI": {"hit": True, "chg": 0.8}}}},
            "2026-09-30": {"headline_p": 0.48},
        }}
        local = {"days": {
            "2026-10-02": {"headline_p": 0.55, "result": None},   # 本次没结算 → 别擦掉远端
            "2026-10-03": {"headline_p": 0.60},
        }}
        merged = mg.merge_docs("output/quant_history.json", remote, local)
        days = merged["days"]
        self.assertEqual(sorted(days), ["2026-09-30", "2026-10-02", "2026-10-03"])
        self.assertEqual(days["2026-10-02"]["headline_p"], 0.55)      # 本次优先
        self.assertTrue(days["2026-10-02"]["result"]["marks"]["^HSI"]["hit"])   # 远端结算保住

    def test_both_settled_local_wins(self):
        remote = {"days": {"2026-10-02": {"result": {"marks": {"^HSI": {"hit": False}}}}}}
        local = {"days": {"2026-10-02": {"result": {"marks": {"^HSI": {"hit": True}}}}}}
        merged = mg.merge_docs("output/quant_history.json", remote, local)
        self.assertTrue(merged["days"]["2026-10-02"]["result"]["marks"]["^HSI"]["hit"])

    def test_deep_merge_fills_local_gaps_for_unknown_json(self):
        remote = {"a": 1, "nested": {"keep": "yes", "both": "remote"}, "only_remote": [1, 2]}
        local = {"a": 2, "nested": {"both": "local"}, "only_local": "x"}
        merged = mg.merge_docs("output/some_new_state.json", remote, local)
        self.assertEqual(merged["a"], 2)
        self.assertEqual(merged["nested"], {"keep": "yes", "both": "local"})
        self.assertEqual(merged["only_remote"], [1, 2])
        self.assertEqual(merged["only_local"], "x")


class TestWholeFilePolicies(unittest.TestCase):
    """HTML / 自校验库文件：整份以本次为准（合并会让 sha256 自校验失效）。"""

    def test_html_takes_local_verbatim(self):
        self.assertEqual(mg.merge_texts("output/latest.html", "<html>remote</html>",
                                        "<html>local</html>"), "<html>local</html>")

    def test_market_db_takes_local_verbatim(self):
        remote = '{"slots": {"0800": {}}, "integrity": {"hash": "REMOTE"}}'
        local = '{"slots": {"1230": {}}, "integrity": {"hash": "LOCAL"}}'
        self.assertEqual(mg.merge_texts("output/market_db/20261004.json", remote, local), local)

    def test_corrupt_remote_falls_back_to_local(self):
        local = '{"version": 1, "items": []}'
        self.assertEqual(mg.merge_texts("output/news_history.json", "not json{{", local), local)

    def test_corrupt_local_keeps_remote(self):
        remote = '{"version": 1,\n "items": []}'
        self.assertEqual(mg.merge_texts("output/news_history.json", remote, "broken"), remote)


class TestOutputFormatting(unittest.TestCase):
    """输出格式必须与各写入方一致，否则每轮运行都产生整文件无意义 diff。"""

    def test_journal_style_matches_save_journal(self):
        doc = {"version": 1, "entries": [{"symbol": "^HSI", "base_date": "2026-10-01"}]}
        text = mg.merge_texts("output/hk7_forecast.json", json.dumps(doc), json.dumps(doc))
        self.assertEqual(text, json.dumps(doc, ensure_ascii=False, sort_keys=True))

    def test_history_style_matches_pipeline_atomic_write(self):
        doc = {"version": 1, "items": [{"title": "标题", "date": "2026-10-04"}],
               "updated_cst": "2026-10-04 09:50:00+0800"}
        text = mg.merge_texts("output/news_history.json", json.dumps(doc), json.dumps(doc))
        self.assertEqual(text, json.dumps(doc, ensure_ascii=False, indent=1))

    def test_trailing_newline_of_local_is_preserved(self):
        doc = {"version": 1, "entries": []}
        with_nl = json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"
        self.assertTrue(mg.merge_texts("output/hk7_forecast.json", with_nl, with_nl).endswith("\n"))
        self.assertFalse(
            mg.merge_texts("output/hk7_forecast.json", with_nl, with_nl.rstrip("\n")).endswith("\n"))

    def test_round_trip_identity_on_repo_files(self):
        """仓库里真实的留痕文件：远端 == 本次时，合并输出必须与原文件逐字节相同。"""
        for name in ("news_history.json", "sentiment_history.json", "quant_history.json",
                     "hk7_forecast.json", "weekly_forecast.json", "push_state.json"):
            path = OUTPUT_DIR / name
            if not path.is_file():
                continue
            original = path.read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertEqual(mg.merge_texts(f"output/{name}", original, original), original)

    def test_push_state_union_keeps_morning_and_evening(self):
        remote = {"version": 1, "days": {"2026-11-09": {"morning": {"pushed": True, "at_cst": "09:17"}}},
                  "updated_cst": "09:17"}
        local = {"version": 1, "days": {"2026-11-09": {"evening": {"pushed": True, "at_cst": "21:20"}}},
                 "updated_cst": "21:20"}
        merged = mg.merge_docs("output/push_state.json", remote, local)
        self.assertTrue(merged["days"]["2026-11-09"]["morning"]["pushed"])
        self.assertTrue(merged["days"]["2026-11-09"]["evening"]["pushed"])

    def test_merge_is_idempotent(self):
        remote = {"version": 1, "items": [{"title": "R", "date": "2026-10-04", "ts": "",
                                           "source": "", "section": ""}],
                  "updated_cst": "a"}
        local = {"version": 1, "items": [{"title": "L", "date": "2026-10-04", "ts": "",
                                          "source": "", "section": ""}],
                 "updated_cst": "b"}
        once = mg.merge_docs("output/news_history.json", remote, local)
        twice = mg.merge_docs("output/news_history.json", once, local)
        self.assertEqual(once, twice)


# ============================================================
# ② 推送脚本（临时 bare 仓库 + 两个克隆，真跑 git，不联网）
# ============================================================
# 注意：这里**不设** GIT_AUTHOR_* / GIT_COMMITTER_*——它们会盖掉 safe_push.sh 里的
# `git config user.name octopus-bot`，那样就测不出「提交身份是否正确」。
# 夹具里自己的提交一律用 `git -c user.name=... commit` 显式指定。
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C.UTF-8",
}


@unittest.skipUnless(GIT, "需要 git 才能跑推送脚本集成测试")
class SafePushFixture(unittest.TestCase):
    """搭一个「远端 + 两个克隆」的小世界，复现 Actions 上的推送竞争。"""

    maxDiff = None

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="octopus-push-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.env = {**os.environ, **GIT_ENV, "HOME": str(self.root)}

    # ---- 基础工具 ----
    def git(self, cwd, *args, check=True):
        result = subprocess.run([GIT, *args], cwd=str(cwd), env=self.env,
                                capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} 失败（{result.returncode}）\n"
                                 f"{result.stdout}\n{result.stderr}")
        return result

    def write(self, cwd, relpath, content):
        path = Path(cwd) / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read(self, cwd, relpath):
        return (Path(cwd) / relpath).read_text(encoding="utf-8")

    def commit(self, cwd, message, paths=("-A",)):
        self.git(cwd, "add", *paths)
        self.git(cwd, "-c", "user.name=octopus-test", "-c", "user.email=test@octopus.ai",
                 "commit", "-q", "-m", message)
        return self.git(cwd, "rev-parse", "HEAD").stdout.strip()

    def seed_remote(self, name="remote", files=None):
        """建 bare 远端 + 种子提交（含被测脚本，与真实仓库布局一致）。"""
        bare = self.root / f"{name}.git"
        self.git(self.root, "init", "--bare", "-q", "-b", "main", str(bare))
        seed = self.root / f"{name}-seed"
        self.git(self.root, "clone", "-q", str(bare), str(seed))
        default = {
            "README.md": "# 章鱼AI\n",
            "output/latest.html": "<html>seed</html>\n",
            "output/news_history.json": json.dumps(
                {"version": 1,
                 "items": [{"title": "种子新闻", "source": "s", "section": "全球头条",
                            "ts": "2026-10-01 08:00", "date": "2026-10-01"}],
                 "updated_cst": "2026-10-01 08:00:00+0800"}, ensure_ascii=False, indent=1),
            "output/market_db/20261004.json": json.dumps(
                {"schema": 1, "slots": {"0800": {"p": 1}},
                 "integrity": {"algo": "sha256", "hash": "SEED"}}, ensure_ascii=False),
        }
        for relpath, content in {**default, **(files or {})}.items():
            self.write(seed, relpath, content)
        self.write(seed, "tools/safe_push.sh", SAFE_PUSH.read_text(encoding="utf-8"))
        self.write(seed, "tools/merge_generated.py",
                   (TOOLS_DIR / "merge_generated.py").read_text(encoding="utf-8"))
        self.commit(seed, "init")
        self.git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
        return bare

    def clone(self, bare, name):
        target = self.root / name
        self.git(self.root, "clone", "-q", str(bare), str(target))
        return target

    def run_push(self, cwd, message="📰 自动更新 2026-10-04 09:50", branch="main",
                 paths=("output/latest.html", "output/news_history.json"),
                 attempts=5, extra_env=None, script="tools/safe_push.sh"):
        cmd = ["bash", script, "--delay", "0", "--attempts", str(attempts),
               "--message", message, "--branch", branch, "--", *paths]
        return subprocess.run(cmd, cwd=str(cwd), env={**self.env, **(extra_env or {})},
                              capture_output=True, text=True)

    def remote_log(self, bare_or_clone):
        self.git(bare_or_clone, "fetch", "-q", "origin")
        out = self.git(bare_or_clone, "log", "--format=%s", "origin/main")
        return [line for line in out.stdout.splitlines() if line]

    # ---- 用例 ----
    def test_recovers_when_pr_merge_lands_during_the_run(self):
        """①号事故：运行期间别人合并 PR（改了 README + 新增文件）→ 必须重放成功且不回退别人。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")          # 工作流检出
        theirs = self.clone(bare, "theirs")      # PR 合并 / 另一个工作流

        self.write(theirs, "README.md", "# 章鱼AI\n\n新增章节（PR #117）\n")
        self.write(theirs, "docs/new.md", "PR 带来的新文件\n")
        self.commit(theirs, "docs: add visual tables (#117)")
        self.git(theirs, "push", "-q", "origin", "HEAD:refs/heads/main")

        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")
        result = self.run_push(mine)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("重放", result.stdout)
        self.assertIn("✅ 推送成功", result.stdout)
        self.assertEqual(self.remote_log(mine)[0], "📰 自动更新 2026-10-04 09:50")
        # 别人的改动一个都没被回退
        self.assertIn("新增章节（PR #117）", self.read(mine, "README.md"))
        self.assertEqual(self.read(mine, "docs/new.md"), "PR 带来的新文件\n")
        self.assertEqual(self.read(mine, "output/latest.html"), "<html>本次生成</html>\n")

    def test_journal_conflict_keeps_entries_from_both_runs(self):
        """②号事故：两个工作流都追加了新闻标题 → 合并后两边条目都在，不丢留痕。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")

        def with_item(title, hhmm):
            doc = json.loads(self.read(mine, "output/news_history.json"))
            doc["items"].append({"title": title, "source": "s", "section": "全球头条",
                                 "ts": f"2026-10-04 {hhmm}", "date": "2026-10-04"})
            doc["updated_cst"] = f"2026-10-04 {hhmm}:00+0800"
            return json.dumps(doc, ensure_ascii=False, indent=1)

        self.write(theirs, "output/news_history.json", with_item("手动推送抓到的", "09:47"))
        self.write(theirs, "output/latest.html", "<html>手动推送版</html>\n")
        self.commit(theirs, "📰 手动抓取推送 2026-10-04")
        self.git(theirs, "push", "-q", "origin", "HEAD:refs/heads/main")

        self.write(mine, "output/news_history.json", with_item("定时任务抓到的", "09:50"))
        self.write(mine, "output/latest.html", "<html>定时任务版</html>\n")
        result = self.run_push(mine)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        doc = json.loads(self.read(mine, "output/news_history.json"))
        titles = [item["title"] for item in doc["items"]]
        self.assertEqual(titles, ["种子新闻", "手动推送抓到的", "定时任务抓到的"])
        # HTML 是整份重新生成的产物 → 以本次（更晚完成的一轮）为准
        self.assertEqual(self.read(mine, "output/latest.html"), "<html>定时任务版</html>\n")

    def test_recovers_when_remote_moves_repeatedly(self):
        """③号事故：远端一直在动（重跑旧 run / 连续推送）→ 多次重放直到成功。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")
        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")

        # git 垫片：前两次 push 之前，先让「别人」推一个提交上去 → 复现连续被拒
        shim_dir = self.root / "bin"
        shim_dir.mkdir()
        armed = self.root / "armed"
        armed.write_text("2", encoding="utf-8")
        shim = shim_dir / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            f'REAL="{GIT}"\n'
            f'ARMED="{armed}"\n'
            f'THEIRS="{theirs}"\n'
            'if [ "${1:-}" = "push" ] && [ "$(cat "$ARMED" 2>/dev/null || echo 0)" -gt 0 ]; then\n'
            '  n=$(cat "$ARMED"); echo $((n - 1)) > "$ARMED"\n'
            '  ( cd "$THEIRS" && echo "moved $n" >> README.md\n'
            '    "$REAL" add -A\n'
            '    "$REAL" -c user.name=t -c user.email=t@e commit -qm "concurrent push $n"\n'
            '    "$REAL" push -q origin HEAD:refs/heads/main ) >/dev/null 2>&1\n'
            'fi\n'
            'exec "$REAL" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)

        result = self.run_push(mine, attempts=5,
                               extra_env={"PATH": f"{shim_dir}{os.pathsep}{self.env['PATH']}"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("推送被拒"), 2)
        self.assertEqual(result.stdout.count("重放完成"), 2)
        self.assertIn("第 3 次尝试", result.stdout)
        log = self.remote_log(mine)
        self.assertEqual(log[0], "📰 自动更新 2026-10-04 09:50")
        self.assertIn("moved 1", self.read(mine, "README.md"))
        self.assertIn("moved 2", self.read(mine, "README.md"))

    def test_no_new_content_commits_nothing(self):
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        before = self.git(mine, "rev-parse", "HEAD").stdout.strip()
        result = self.run_push(mine)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("无新内容，跳过提交", result.stdout)
        self.assertEqual(self.git(mine, "rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(len(self.remote_log(mine)), 1)

    def test_identical_upstream_content_does_not_duplicate_commit(self):
        """远端已推了同样内容（重跑同一轮）→ 不产生重复提交，作业仍算成功。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")
        for cwd in (mine, theirs):
            self.write(cwd, "output/latest.html", "<html>同样的内容</html>\n")
        self.commit(theirs, "📰 自动更新（另一次运行）")
        self.git(theirs, "push", "-q", "origin", "HEAD:refs/heads/main")

        result = self.run_push(mine)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("远端已包含相同内容", result.stdout)
        log = self.remote_log(mine)
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0], "📰 自动更新（另一次运行）")

    def test_permission_style_rejection_fails_fast(self):
        """保护分支 / 钩子拒绝不是「远端前进」→ 立即失败，不空转 5 次。"""
        bare = self.seed_remote()
        hook = bare / "hooks" / "pre-receive"
        hook.write_text("#!/usr/bin/env bash\n"
                        "echo 'GH006: Protected branch rule update failed' >&2\nexit 1\n",
                        encoding="utf-8")
        hook.chmod(0o755)
        mine = self.clone(bare, "mine")
        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")

        result = self.run_push(mine, attempts=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("不是「远端已前进」类型", result.stdout + result.stderr)
        self.assertNotIn("重放", result.stdout)
        self.assertIn("GH006", result.stdout + result.stderr)

    def test_gives_up_after_attempts_and_says_so(self):
        """远端永远在动 → 到次数上限后明确报错（并提示重跑），不静默成功。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")
        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")

        shim_dir = self.root / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            f'REAL="{GIT}"\n'
            f'THEIRS="{theirs}"\n'
            'if [ "${1:-}" = "push" ]; then\n'
            '  ( cd "$THEIRS" && echo x >> README.md && "$REAL" add -A &&\n'
            '    "$REAL" -c user.name=t -c user.email=t@e commit -qm noise &&\n'
            '    "$REAL" push -q origin HEAD:refs/heads/main ) >/dev/null 2>&1\n'
            'fi\n'
            'exec "$REAL" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)

        result = self.run_push(mine, attempts=2,
                               extra_env={"PATH": f"{shim_dir}{os.pathsep}{self.env['PATH']}"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("连续 2 次推送被拒", result.stdout + result.stderr)

    def test_deleted_generated_file_is_replayed(self):
        """本次删掉的文件，重放后也必须是删除（而不是被远端版本复活）。"""
        bare = self.seed_remote(files={"output/daily_report_20260101.html": "<html>旧</html>\n"})
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")
        self.write(theirs, "README.md", "# 章鱼AI\n\n别人的改动\n")
        self.commit(theirs, "docs: 别人的改动")
        self.git(theirs, "push", "-q", "origin", "HEAD:refs/heads/main")

        (mine / "output/daily_report_20260101.html").unlink()
        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")
        result = self.run_push(mine, paths=("output/latest.html", "output/daily_report_*.html"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((mine / "output/daily_report_20260101.html").exists())
        self.assertIn("别人的改动", self.read(mine, "README.md"))

    def test_market_db_self_hashed_file_takes_ours(self):
        """带 sha256 自校验的库文件不能内容级合并 → 整份取本次（哈希才是自洽的）。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")
        self.write(theirs, "output/market_db/20261004.json", json.dumps(
            {"schema": 1, "slots": {"0800": {"p": 9}},
             "integrity": {"algo": "sha256", "hash": "REMOTE"}}, ensure_ascii=False))
        self.commit(theirs, "🗄️ 市场数据库（远端）")
        self.git(theirs, "push", "-q", "origin", "HEAD:refs/heads/main")

        local_doc = json.dumps({"schema": 1, "slots": {"1230": {"p": 2}},
                                "integrity": {"algo": "sha256", "hash": "LOCAL"}},
                               ensure_ascii=False)
        self.write(mine, "output/market_db/20261004.json", local_doc)
        result = self.run_push(mine, message="🗄️ 市场数据库 2026-10-04 12:30",
                               paths=("output/market_db/",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.read(mine, "output/market_db/20261004.json"))
                         ["integrity"]["hash"], "LOCAL")

    def test_replay_leaves_clean_state_and_keeps_commit_identity(self):
        """重放后：不残留 rebase 状态、工作区干净、提交身份与信息与原来一致。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        theirs = self.clone(bare, "theirs")
        self.write(theirs, "README.md", "# 章鱼AI\n\n别人的改动\n")
        theirs_sha = self.commit(theirs, "docs: 别人的改动")
        self.git(theirs, "push", "-q", "origin", "HEAD:refs/heads/main")

        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")
        result = self.run_push(mine, message="📰 自动更新 2026-10-04 09:50")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertEqual(self.git(mine, "status", "--porcelain").stdout.strip(), "")
        for marker in ("rebase-merge", "rebase-apply"):
            self.assertFalse((mine / ".git" / marker).exists(), f"残留 {marker}")
        show = self.git(mine, "show", "-s", "--format=%an|%ae|%cn|%ce|%s", "HEAD").stdout.strip()
        self.assertEqual(show, "octopus-bot|bot@octopus.ai|octopus-bot|bot@octopus.ai|"
                               "📰 自动更新 2026-10-04 09:50")
        # 重放后的提交直接长在「别人那次提交」之上，不是长在旧检出上
        parents = self.git(mine, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
        self.assertEqual(parents[1], theirs_sha)
        head = self.git(mine, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self.git(mine, "rev-parse", "origin/main").stdout.strip(), head)

    def test_pushes_to_declared_branch_not_current_head_name(self):
        """检出为分离 HEAD（重跑旧 run 常见）时也要推到目标分支。"""
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        head = self.git(mine, "rev-parse", "HEAD").stdout.strip()
        self.git(mine, "checkout", "-q", "--detach", head)
        self.write(mine, "output/latest.html", "<html>本次生成</html>\n")
        result = self.run_push(mine, branch="main")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.remote_log(mine)[0], "📰 自动更新 2026-10-04 09:50")

    def test_missing_message_or_paths_is_usage_error(self):
        bare = self.seed_remote()
        mine = self.clone(bare, "mine")
        no_message = subprocess.run(["bash", "tools/safe_push.sh", "--branch", "main",
                                     "--", "output/latest.html"],
                                    cwd=str(mine), env=self.env, capture_output=True, text=True)
        self.assertEqual(no_message.returncode, 2)
        no_paths = subprocess.run(["bash", "tools/safe_push.sh", "-m", "x"],
                                  cwd=str(mine), env=self.env, capture_output=True, text=True)
        self.assertEqual(no_paths.returncode, 2)


# ============================================================
# ③ 工作流接线（纯文本解析，不依赖 pyyaml）
# ============================================================
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
PUSHING_WORKFLOWS = ("octopus-daily.yml", "octopus-evening.yml", "manual.yml", "market-db.yml")
REPORT_WORKFLOWS = ("octopus-daily.yml", "octopus-evening.yml", "manual.yml")
# 每次运行会写、必须跟着日报一起提交回库的留痕文件（漏一个 = 命中率统计缺样本）
JOURNAL_SOURCES = ("output/pipeline.py", "output/hk_seven_day.py",
                   "output/octopus_weekly.py", "output/octopus_quant/engine.py")
# 只读的素材 / 词库文件：虽然也叫 *_FILENAME，但不是每轮生成的留痕，不需要提交
READ_ONLY_JSON_ASSETS = {"stock_memes.json"}


def _join_continuations(lines, start):
    """从 start 行开始，把以反斜杠续行的命令拼成一行。"""
    parts = [lines[start].strip()]
    index = start
    while parts[-1].endswith("\\") and index + 1 < len(lines):
        parts[-1] = parts[-1][:-1].strip()
        index += 1
        parts.append(lines[index].strip())
    return " ".join(part for part in parts if part), index


def _push_invocations(text):
    """抽出工作流里所有 tools/safe_push.sh 调用，返回 [(完整命令, pathspec 列表)]。"""
    lines = text.splitlines()
    found = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        # 只认真正的命令行：注释里提到 tools/safe_push.sh 不算一次调用
        if "tools/safe_push.sh" in line and not line.startswith("#"):
            command, index = _join_continuations(lines, index)
            # 分隔符是独立的一个「--」（不能按 "--" 切，--branch / --message 也含它）
            specs = command.split(" -- ", 1)[1].split() if " -- " in command else []
            found.append((command, specs))
        index += 1
    return found


def _artifact_paths(text):
    """抽出「推送失败兜底」那一步 upload-artifact 的 path 列表。"""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "unpushed-" in line:
            for offset in range(index, min(index + 12, len(lines))):
                if lines[offset].strip() == "path: |":
                    indent = len(lines[offset]) - len(lines[offset].lstrip())
                    paths = []
                    for tail in lines[offset + 1:]:
                        if not tail.strip():
                            continue
                        if (len(tail) - len(tail.lstrip())) <= indent:
                            break
                        paths.append(tail.strip())
                    return paths
    return []


def _concurrency(text):
    match = re.search(r"^concurrency:\s*\n\s+group:\s*(\S+)\s*\n\s+cancel-in-progress:\s*(\S+)",
                      text, re.MULTILINE)
    return match.groups() if match else (None, None)


class TestToolsShipInRepo(unittest.TestCase):
    """被测的两个工具必须在仓库里（工作流是从仓库根目录调用它们的）。"""

    def test_merge_tool_and_script_ship_in_repo(self):
        for relpath in ("tools/safe_push.sh", "tools/merge_generated.py"):
            with self.subTest(path=relpath):
                self.assertTrue((REPO_ROOT / relpath).is_file())
        self.assertIn("merge_generated.py", SAFE_PUSH.read_text(encoding="utf-8"))


class TestWorkflowWiring(unittest.TestCase):
    """三个会推送的工作流必须都用同一把「安全推送」，且提交的留痕清单不许漂移。

    改 `.github/workflows/` 需要 GitHub App 的 **Workflows 写权限**；权限没开时这部分
    改动由人工粘贴，本组会整组跳过（而不是留一条红分支）。**粘贴之后自动生效**：
    届时清单漂移、裸 `git push` 复活、锁没加上，都会在这里红给你看。
    """

    def setUp(self):
        self.texts = {}
        for name in PUSHING_WORKFLOWS:
            path = WORKFLOW_DIR / name
            self.assertTrue(path.is_file(), f"缺少工作流 {name}")
            self.texts[name] = path.read_text(encoding="utf-8")
        unwired = [name for name, text in self.texts.items() if not _push_invocations(text)]
        if unwired:
            self.skipTest("工作流改动尚未应用到 .github/workflows/（"
                          + ", ".join(sorted(unwired))
                          + " 还没调用 tools/safe_push.sh）：该目录需要 Workflows 写权限，"
                            "由人工粘贴；粘贴后本组自动生效")

    def test_every_pushing_workflow_uses_safe_push(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertEqual(len(_push_invocations(text)), 1, "应当只有一处提交推送")
                bare_pushes = [line.strip() for line in text.splitlines()
                               if re.match(r"^git push\b", line.strip())]
                self.assertEqual(bare_pushes, [],
                                 "不该再出现裸 git push（被拒即整步失败、生成物全丢）")

    def test_report_workflows_share_one_concurrency_lock(self):
        groups = {}
        for name in REPORT_WORKFLOWS:
            group, cancel = _concurrency(self.texts[name])
            groups[name] = group
            self.assertEqual(cancel, "false", f"{name} 不该取消在跑的那一轮（会丢留痕）")
        self.assertEqual(len(set(groups.values())), 1,
                         f"两个日报工作流必须共用一把锁，否则并行推送必被拒：{groups}")
        self.assertTrue(groups[REPORT_WORKFLOWS[0]])

    def test_market_db_keeps_its_own_lock(self):
        group, cancel = _concurrency(self.texts["market-db.yml"])
        self.assertEqual(group, "market-db")
        self.assertEqual(cancel, "false")

    def test_journal_files_defined_in_sources_are_all_committed(self):
        """源码里每新增一个留痕文件，工作流的提交清单必须跟上（否则留痕悄悄丢失）。"""
        journals = set()
        for relpath in JOURNAL_SOURCES:
            source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
            journals.update(re.findall(r"^[A-Z_]*FILENAME[A-Z_]*\s*=\s*\"([^\"]+\.json)\"",
                                       source, re.MULTILINE))
        journals -= READ_ONLY_JSON_ASSETS
        # 新增留痕文件时这里会红：要么把它加进两个日报工作流的提交清单（正常情况），
        # 要么确认它是只读素材、加进 READ_ONLY_JSON_ASSETS（别默默漏提交）
        self.assertEqual(journals, {"sentiment_history.json", "news_history.json",
                                    "quant_history.json", "hk7_forecast.json",
                                    "weekly_forecast.json"})
        for name in REPORT_WORKFLOWS:
            specs = _push_invocations(self.texts[name])[0][1]
            with self.subTest(workflow=name):
                for journal in sorted(journals):
                    self.assertIn(f"output/{journal}", specs)

    def test_report_workflows_commit_identical_pathspecs(self):
        baseline = sorted(_push_invocations(self.texts[REPORT_WORKFLOWS[0]])[0][1])
        for name in REPORT_WORKFLOWS[1:]:
            with self.subTest(workflow=name):
                self.assertEqual(sorted(_push_invocations(self.texts[name])[0][1]), baseline,
                                 "早盘/晚间/手动三条日报流水线跑的是同一个 pipeline，提交清单必须一致")

    def test_every_pathspec_matches_something_in_the_repo(self):
        """清单里写错文件名会静默丢提交（git add 的通配符没匹配到也不报错）。"""
        for name, text in self.texts.items():
            for _, specs in _push_invocations(text):
                for spec in specs:
                    with self.subTest(workflow=name, spec=spec):
                        matches = glob.glob(str(REPO_ROOT / spec))
                        self.assertTrue(matches or (REPO_ROOT / spec).exists(),
                                        f"{spec} 在仓库里既不是文件也不匹配任何文件")

    def test_fallback_artifact_covers_the_same_files(self):
        """推送最终失败时，兜底 Artifact 必须把同一批生成物留下来。"""
        for name in REPORT_WORKFLOWS:
            specs = set(_push_invocations(self.texts[name])[0][1])
            artifact = set(_artifact_paths(self.texts[name]))
            with self.subTest(workflow=name):
                self.assertTrue(artifact, "缺少推送失败兜底 Artifact 步骤")
                self.assertEqual(specs, artifact)
                self.assertIn("if: failure()", self.texts[name])

if __name__ == "__main__":
    unittest.main(verbosity=2)
