"""运行依赖回归：真实子进程启动流水线，不 mock requests / jieba、不联网。"""
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeDependencyTests(unittest.TestCase):
    def test_report_workflows_install_shared_requirements(self):
        for name in ("octopus-daily.yml", "manual.yml"):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github" / "workflows" / name).read_text()
                self.assertIn(
                    "python -m pip install --quiet -r requirements.txt", workflow
                )
                self.assertNotIn("pip install --quiet requests", workflow)

    def test_pipeline_help_with_real_dependencies(self):
        result = subprocess.run(
            [sys.executable, "output/pipeline.py", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--no-push", result.stdout)

    def test_finance_analysis_with_real_jieba(self):
        result = subprocess.run(
            [sys.executable, "-c", (
                "from output.finance_analysis import analyze_finance_item; "
                "r = analyze_finance_item('国务院发布新能源汽车产业发展规划'); "
                "assert r['concepts'], r; "
                "assert r['vocabulary_terms'], r; "
                "assert abs(r['positive_probability'] + "
                "r['negative_probability'] - 100) < 0.01, r"
            )],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
