from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.config import load_config, resolve_prompt_path, agent_map
from engine.context_scanner import ContextScanner, is_sensitive_path
from engine.orchestrator import Orchestrator, load_report, find_run_reports
from engine.quality_gates import run_quality_gate


class EngineTests(unittest.TestCase):
    def test_platform_template_is_default_config_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loaded = load_config(root)
            self.assertIn(loaded.source, {"platform", "default"})
            self.assertNotEqual(loaded.source, "skill")
            if loaded.path:
                self.assertIn("templates", loaded.path)

    def test_prompt_resolves_from_platform_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loaded = load_config(root)
            agents = agent_map(loaded.config)
            prompt = resolve_prompt_path(root, loaded.path, agents["tech-lead"])
            self.assertIn("templates/agents/tech-lead.md", str(prompt))

    def test_context_scanner_excludes_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
            self.assertTrue(is_sensitive_path(".env"))
            text = ContextScanner(root).scan("")
            self.assertIn("src/app.py", text)
            self.assertNotIn("SECRET=1", text)

    def test_quality_gate_command_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_quality_gate(
                {"name": "smoke", "type": "command", "command": "python3 -c \"print('ok')\"", "required": True},
                Path(tmp),
                "test-run",
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.exit_code, 0)

    def test_orchestrator_runs_mock_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "Approve"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
  - id: accept
    name: Accept
    type: human_review
quality_gates:
  - name: smoke
    type: command
    command: "python3 -c \\"print('ok')\\""
    required: true
    max_retries: 0
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            self.assertEqual(report.status, "completed")
            self.assertEqual(report.config_source, "project")
            self.assertIn("tech-lead-output.md", report.artifacts)
            self.assertTrue((Path(report.output_dir) / "report.json").exists())

    def test_loopback_feedback_injects_output_content(self) -> None:
        """loopback 反馈包含结构化的 per-agent 信息"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "error: compilation failed"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
    loopback_to: develop
    loopback_trigger: "error:"
    max_retries: 1
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            self.assertEqual(report.status, "failed")
            output_dir = Path(report.output_dir)
            feedback_file = output_dir / "loopback-feedback-develop-1.md"
            self.assertTrue(feedback_file.exists(), "loopback feedback file should be created")
            feedback_content = feedback_file.read_text(encoding="utf-8")
            self.assertIn("Loopback 反馈", feedback_content)
            self.assertIn("Agent: dev", feedback_content)
            self.assertIn("Runtime: Mock", feedback_content)
            self.assertIn("error: compilation failed", feedback_content)
            self.assertIn("第 1 次重试", feedback_content)

    def test_loopback_cross_stage_feedback(self) -> None:
        """qa→develop 的 loopback 反馈包含 qa agent 的实际输出"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "done"
  MockQA:
    cli: mock
    response: "FAILED: 2 tests did not pass"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
  - name: qa
    runtime_id: MockQA
    role: tester
    prompt: agents/qa.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
  - id: qa
    name: QA
    agents: [qa]
    input: [requirement, tech-lead-output.md]
    output:
      qa: test-report.md
    loopback_to: develop
    loopback_trigger: ["FAILED", "ERROR"]
    max_retries: 1
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            (root / ".ai" / "agents" / "qa.md").write_text("You are qa.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("implement feature", yes=True)
            self.assertEqual(report.status, "failed")
            output_dir = Path(report.output_dir)
            feedback_file = output_dir / "loopback-feedback-qa-1.md"
            self.assertTrue(feedback_file.exists(), "qa loopback feedback file should exist")
            feedback_content = feedback_file.read_text(encoding="utf-8")
            self.assertIn("Agent: qa", feedback_content)
            self.assertIn("Runtime: MockQA", feedback_content)
            self.assertIn("FAILED: 2 tests did not pass", feedback_content)


    def test_parallel_agents_execute_concurrently(self) -> None:
        """测试并行 stage 中多个 agent 同时执行"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "done"
agents:
  - name: qa
    runtime_id: Mock
    role: tester
    prompt: agents/qa.md
  - name: reviewer
    runtime_id: Mock
    role: reviewer
    prompt: agents/reviewer.md
pipeline:
  - id: verify
    name: Verify
    parallel: true
    agents: [qa, reviewer]
    input: requirement
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "qa.md").write_text("You are qa.", encoding="utf-8")
            (root / ".ai" / "agents" / "reviewer.md").write_text("You are reviewer.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            self.assertEqual(report.status, "completed")
            stage_run = report.stages[0] if report.stages else None
            self.assertIsNotNone(stage_run)
            self.assertTrue(stage_run.is_parallel)
            self.assertEqual(len(stage_run.agents), 2)
            for agent_run in stage_run.agents:
                self.assertEqual(agent_run.status, "completed")

    def test_quality_gates_loop_retries_on_failure(self) -> None:
        """测试质量门禁失败后的重试循环"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "fixed"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
quality_gates:
  - name: lint
    type: command
    command: "exit 1"
    required: true
    max_retries: 2
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            # 质量门禁始终失败，且达到最大重试次数
            self.assertEqual(report.status, "failed")
            develop_stages = [s for s in report.stages if s.stage_id == "develop"]
            # 应有多于 1 个 develop stage（初始 + 重试）
            self.assertGreaterEqual(len(develop_stages), 1)

    def test_quality_gates_pass_on_first_try(self) -> None:
        """测试质量门禁首次通过时不再重试"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "done"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
quality_gates:
  - name: lint
    type: command
    command: "python3 -c \\"print('pass')\\""
    required: true
    max_retries: 2
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            self.assertEqual(report.status, "completed")
            develop_stages = [s for s in report.stages if s.stage_id == "develop"]
            # 质量门禁通过，应只有 1 个 develop stage（无重试）
            self.assertEqual(len(develop_stages), 1)
            # 检查 quality_gates 结果
            stage_run = develop_stages[0]
            self.assertEqual(len(stage_run.quality_gates), 1)
            self.assertEqual(stage_run.quality_gates[0].status, "passed")

    def test_validate_production_config_no_production_mode(self) -> None:
        """validate_production_config: 非生产模式不抛出异常"""
        from engine.config import validate_production_config

        config = {
            "runner": {"production_mode": False},
            "worktree": {"enabled": False},
            "quality_gates": [],
        }
        # 不应抛出异常
        validate_production_config(config)

    def test_validate_production_config_require_worktree_fails(self) -> None:
        """validate_production_config: 要求 worktree 但未启用时抛出 ConfigError"""
        from engine.config import ConfigError, validate_production_config

        config = {
            "runner": {"production_mode": True, "require_worktree": True},
            "worktree": {"enabled": False},
        }
        with self.assertRaises(ConfigError) as ctx:
            validate_production_config(config)
        self.assertIn("worktree", str(ctx.exception))

    def test_validate_production_config_require_verify_cmd_fails(self) -> None:
        """validate_production_config: 要求 verify_cmd 但无 quality_gates 时抛出 ConfigError"""
        from engine.config import ConfigError, validate_production_config

        config = {
            "runner": {"production_mode": True, "require_verify_cmd": True},
            "worktree": {"enabled": True},
            "quality_gates": [],
        }
        with self.assertRaises(ConfigError) as ctx:
            validate_production_config(config)
        self.assertIn("quality_gates", str(ctx.exception))

    def test_validate_production_config_passes_when_all_conditions_met(self) -> None:
        """validate_production_config: 条件全部满足时不抛出异常"""
        from engine.config import validate_production_config

        config = {
            "runner": {"production_mode": True, "require_worktree": True, "require_verify_cmd": True},
            "worktree": {"enabled": True},
            "quality_gates": [{"name": "lint", "command": "pylint"}],
        }
        validate_production_config(config)

    def test_loopback_trigger_with_regex_pattern(self) -> None:
        """测试正则匹配触发 loopback 机制"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "Build FAILED with error code 1"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
    loopback_to: develop
    loopback_trigger: "regex:FAILED"
    max_retries: 1
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            # 由于 loopback 且超过 max_retries=1，最终失败
            self.assertEqual(report.status, "failed")

    def test_loopback_max_retries_zero_skips_loopback(self) -> None:
        """max_retries=0 时触发 loopback 直接报错，导致运行失败"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "error: detected"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
    loopback_to: develop
    loopback_trigger: "error:"
    max_retries: 0
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)
            self.assertEqual(report.status, "failed")

    def test_quality_gate_threshold_comparison(self) -> None:
        """测试阈值类型质量门禁的比较"""
        from engine.quality_gates import OPS

        # 验证所有比较操作符
        self.assertTrue(OPS[">="](90, 80))
        self.assertTrue(OPS[">"](90, 80))
        self.assertTrue(OPS["<="](70, 80))
        self.assertTrue(OPS["<"](70, 80))
        self.assertTrue(OPS["=="](80, 80))
        self.assertFalse(OPS[">="](70, 80))

    def test_quality_gate_threshold_type_passes(self) -> None:
        """阈值类型质量门禁：覆盖率达标时通过"""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "calc.py").write_text("print('Coverage: 95.2%')\n", encoding="utf-8")
            result = run_quality_gate(
                {
                    "name": "coverage",
                    "type": "threshold",
                    "command": "python3 calc.py",
                    "parse": "regex:Coverage:\\s*([\\d.]+)%",
                    "operator": ">=",
                    "threshold": 80,
                    "required": True,
                },
                root,
                "test-run",
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.actual, 95.2)
            self.assertEqual(result.threshold, 80)

    def test_context_scanner_detects_python_project_type(self) -> None:
        """ContextScanner 检测 Python 项目类型"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            text = ContextScanner(root).scan("")
            self.assertIn("python", text.lower())

    def test_agent_runner_mock_produces_output(self) -> None:
        """AgentRunner mock 模式产生输出文件"""
        from engine.agent_runner import AgentRunner
        from engine.models import AgentDefinition

        config = {
            "runtimes": {"Mock": {"cli": "mock", "response": "test output"}},
            "runner": {},
        }
        runner = AgentRunner(config)
        agent = AgentDefinition(name="test-agent", runtime_id="Mock", role="tester")
        runtime = {"cli": "mock", "response": "mock output success"}
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            output_file = cwd / "output.md"
            raw_log = cwd / "raw.log"
            result = runner.run(
                "run-1", "stage-1", agent, runtime, "do something", cwd, output_file, raw_log
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.exit_code, 0)
            self.assertTrue(output_file.exists())
            self.assertIn("mock output success", output_file.read_text(encoding="utf-8"))

    def test_load_report_reads_valid_json(self) -> None:
        """load_report 从 JSON 文件恢复 RunReport"""
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text('{"run_id":"r1","status":"completed","requirement":"test","project_root":"/tmp","output_dir":"/tmp","config_source":"default"}', encoding="utf-8")
            report = load_report(report_path)
            self.assertEqual(report.run_id, "r1")
            self.assertEqual(report.status, "completed")

    def test_load_report_migrates_legacy_agent_runtime_id(self) -> None:
        """旧 report 里的 agent 缺 runtime_id 时，读取期补 legacy，避免列表页 500"""
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "run_id": "legacy-run",
                        "status": "completed",
                        "requirement": "test",
                        "project_root": "/tmp",
                        "output_dir": "/tmp",
                        "config_source": "default",
                        "stages": [
                            {
                                "stage_id": "develop",
                                "stage_name": "Develop",
                                "is_parallel": False,
                                "type": "agent",
                                "agents": [{"agent_name": "dev", "status": "completed"}],
                                "quality_gates": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = load_report(report_path)
            self.assertEqual(report.stages[0].agents[0].runtime_id, "legacy")

    def test_find_run_reports_returns_sorted(self) -> None:
        """find_run_reports 返回排序后的报告文件"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / ".ai" / "team-output"
            run1 = output_dir / "run-1"
            run1.mkdir(parents=True)
            (run1 / "report.json").write_text('{"run_id":"r1"}', encoding="utf-8")
            run2 = output_dir / "run-2"
            run2.mkdir()
            (run2 / "report.json").write_text('{"run_id":"r2"}', encoding="utf-8")
            reports = find_run_reports(root)
            self.assertEqual(len(reports), 2)

    def test_find_run_reports_empty_when_no_output(self) -> None:
        """无输出目录时返回空列表"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = find_run_reports(root)
            self.assertEqual(reports, [])

    def test_orchestrator_with_git_diff_input(self) -> None:
        """测试 git-diff 输入类型能正常工作"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, capture_output=True, check=True)
            (root / "README.md").write_text("init\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "done"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: [requirement, "git-diff"]
    output:
      dev: tech-lead-output.md
  - id: accept
    name: Accept
    type: human_review
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("implement feature", yes=True)
            self.assertEqual(report.status, "completed")

    def test_orchestrator_with_code_apply_stage(self) -> None:
        """测试 code_apply stage 类型正常工作"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "### 新增文件: `output.txt`\\n```text\\nhello world\\n```"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
  - id: code_apply
    name: Code Apply
    type: code_apply
    input: [tech-lead-output.md]
  - id: accept
    name: Accept
    type: human_review
worktree:
  enabled: false
quality_gates: []
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("create a file", yes=True)
            self.assertEqual(report.status, "completed")
            stage_ids = [s.stage_id for s in report.stages]
            self.assertIn("code_apply", stage_ids)

    def test_orchestrator_with_skip_stages(self) -> None:
        """测试 skip_stages 跳过指定 stage"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "done"
agents:
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
  - id: review
    name: Review
    agents: [dev]
    input: [requirement, tech-lead-output.md]
    output:
      dev: review.md
  - id: accept
    name: Accept
    type: human_review
worktree:
  enabled: false
quality_gates: []
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("test", yes=True, skip_stages=["review"])
            self.assertEqual(report.status, "completed")
            # skip_stages 仍然出现在 stages 中，但状态为 skipped
            review_stages = [s for s in report.stages if s.stage_id == "review"]
            self.assertEqual(len(review_stages), 1)
            self.assertEqual(review_stages[0].status, "skipped")

    def test_plan_confirm_skips_when_gap_analysis_has_no_blockers(self) -> None:
        """plan_confirm 在无 blocker 时自动 skipped，并继续后续 stage"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "No blocker. 需求清晰，可以继续。"
agents:
  - name: brainstormer
    runtime_id: Mock
    role: brainstormer
    prompt: agents/brainstormer.md
  - name: devils-advocate
    runtime_id: Mock
    role: reviewer
    prompt: agents/devils-advocate.md
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: plan
    name: Plan
    agents: [brainstormer, devils-advocate]
    input: requirement
    output:
      brainstormer: brainstorm.md
      devils-advocate: gap-analysis.md
  - id: plan_confirm
    name: Plan Confirm
    type: human_review
    input: [requirement, brainstorm.md, gap-analysis.md]
    skip_if_no_blocker: true
    blocker_source: gap-analysis.md
    output_file: requirement-decisions.md
  - id: develop
    name: Develop
    agents: [dev]
    input: [requirement, requirement-decisions.md]
    output:
      dev: tech-lead-output.md
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            for name in ["brainstormer", "devils-advocate", "dev"]:
                (root / ".ai" / "agents" / f"{name}.md").write_text(f"You are {name}.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("add hello", yes=False)

            self.assertEqual(report.status, "completed")
            stages = {stage.stage_id: stage for stage in report.stages}
            self.assertEqual(stages["plan_confirm"].status, "skipped")
            decisions = Path(report.output_dir) / "requirement-decisions.md"
            self.assertTrue(decisions.exists())
            self.assertIn("无 blocker", decisions.read_text(encoding="utf-8"))

    def test_plan_confirm_waits_when_gap_analysis_has_blockers_and_keeps_checkpoint(self) -> None:
        """plan_confirm 检测到 blocker 时进入 waiting，并保留 checkpoint 供恢复"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "Blocker: 需要确认 OAuth2 还是 JWT"
agents:
  - name: devils-advocate
    runtime_id: Mock
    role: reviewer
    prompt: agents/devils-advocate.md
pipeline:
  - id: plan
    name: Plan
    agents: [devils-advocate]
    input: requirement
    output:
      devils-advocate: gap-analysis.md
  - id: plan_confirm
    name: Plan Confirm
    type: human_review
    input: [requirement, gap-analysis.md]
    skip_if_no_blocker: true
    blocker_source: gap-analysis.md
    output_file: requirement-decisions.md
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "devils-advocate.md").write_text("You are reviewer.", encoding="utf-8")

            with patch("sys.stdin.isatty", return_value=False):
                report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("auth", yes=False)

            self.assertEqual(report.status, "waiting")
            stages = {stage.stage_id: stage for stage in report.stages}
            self.assertEqual(stages["plan_confirm"].status, "waiting")
            output_dir = Path(report.output_dir)
            self.assertTrue((output_dir / "checkpoint.json").exists())
            decisions = (output_dir / "requirement-decisions.md").read_text(encoding="utf-8")
            self.assertIn("waiting", decisions)
            self.assertIn("Blocker", decisions)

    def test_resume_accepts_waiting_plan_confirm_and_continues(self) -> None:
        """waiting 的 plan_confirm 可通过 resume + yes 从原 checkpoint 继续"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Reviewer:
    cli: mock
    response: "Blocker: 需要确认 OAuth2 还是 JWT"
  Dev:
    cli: mock
    response: "done"
agents:
  - name: devils-advocate
    runtime_id: Reviewer
    role: reviewer
    prompt: agents/devils-advocate.md
  - name: dev
    runtime_id: Dev
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: plan
    name: Plan
    agents: [devils-advocate]
    input: requirement
    output:
      devils-advocate: gap-analysis.md
  - id: plan_confirm
    name: Plan Confirm
    type: human_review
    input: [requirement, gap-analysis.md]
    skip_if_no_blocker: true
    blocker_source: gap-analysis.md
    output_file: requirement-decisions.md
  - id: develop
    name: Develop
    agents: [dev]
    input: [requirement, requirement-decisions.md]
    output:
      dev: tech-lead-output.md
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "devils-advocate.md").write_text("You are reviewer.", encoding="utf-8")
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")

            with patch("sys.stdin.isatty", return_value=False):
                waiting = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("auth", run_id="resume-plan-confirm", yes=False)
            self.assertEqual(waiting.status, "waiting")
            self.assertTrue((Path(waiting.output_dir) / "checkpoint.json").exists())

            resumed = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("auth", run_id="resume-plan-confirm", yes=True, resume=True)

            self.assertEqual(resumed.status, "completed")
            self.assertFalse((Path(resumed.output_dir) / "checkpoint.json").exists())
            self.assertTrue((Path(resumed.output_dir) / "tech-lead-output.md").exists())

    def test_execution_mode_serial_overrides_parallel_stage(self) -> None:
        """全局 serial 模式下，即使 stage.parallel=true 也串行执行"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "done"
agents:
  - name: qa
    runtime_id: Mock
    role: tester
    prompt: agents/qa.md
  - name: reviewer
    runtime_id: Mock
    role: reviewer
    prompt: agents/reviewer.md
pipeline:
  execution_mode: serial
  stages:
    - id: verify
      name: Verify
      parallel: true
      agents: [qa, reviewer]
      input: requirement
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "qa.md").write_text("You are qa.", encoding="utf-8")
            (root / ".ai" / "agents" / "reviewer.md").write_text("You are reviewer.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)

            self.assertEqual(report.status, "completed")
            self.assertFalse(report.stages[0].is_parallel)
            self.assertEqual([agent.agent_name for agent in report.stages[0].agents], ["qa", "reviewer"])

    def test_orchestrator_auto_splits_large_requirement_into_units(self) -> None:
        """超过阈值的需求先拆成 units，再逐单元执行 pipeline 并写入 report"""
        splitter_response = json.dumps(
            {
                "units": [
                    {
                        "id": "unit-1",
                        "title": "认证",
                        "description": "实现登录",
                        "priority": 1,
                        "depends_on": [],
                        "requirement_text": "实现登录",
                    },
                    {
                        "id": "unit-2",
                        "title": "个人中心",
                        "description": "实现资料页",
                        "priority": 2,
                        "depends_on": ["unit-1"],
                        "requirement_text": "实现资料页",
                    },
                ]
            },
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                f"""
runtimes:
  Splitter:
    cli: mock
    response: '{splitter_response}'
  Mock:
    cli: mock
    response: "done"
agents:
  - name: solution-architect
    runtime_id: Splitter
    role: architect
    prompt: agents/solution-architect.md
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
  - name: qa
    runtime_id: Mock
    role: tester
    prompt: agents/qa.md
  - name: reviewer
    runtime_id: Mock
    role: reviewer
    prompt: agents/reviewer.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
  - id: qa
    name: QA
    agents: [qa]
    input: [requirement, tech-lead-output.md]
    output:
      qa: test-report.md
  - id: review
    name: Review
    agents: [reviewer]
    input: [requirement, tech-lead-output.md, test-report.md]
    output:
      reviewer: review-report.md
runner:
  auto_split_requirements: true
  context_threshold_chars: 10
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            for name in ["solution-architect", "dev", "qa", "reviewer"]:
                (root / ".ai" / "agents" / f"{name}.md").write_text(f"You are {name}.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("x" * 30, yes=True)

            self.assertEqual(report.status, "completed")
            self.assertEqual(report.mode, "multi-unit")
            self.assertEqual([unit.unit_id for unit in report.units], ["unit-1", "unit-2"])
            self.assertTrue(all(unit.status == "completed" for unit in report.units))
            self.assertTrue((Path(report.output_dir) / "requirement-units.json").exists())
            self.assertTrue((Path(report.output_dir) / "requirement-units" / "unit-1" / "test-report.md").exists())

    def test_orchestrator_runs_requirement_units_by_dependency_before_priority(self) -> None:
        """multi-unit 执行按 depends_on 拓扑排序，priority 只作为同层排序"""
        splitter_response = json.dumps(
            {
                "units": [
                    {
                        "id": "api",
                        "title": "API",
                        "description": "实现 API",
                        "priority": 1,
                        "depends_on": ["db"],
                        "requirement_text": "实现 API",
                    },
                    {
                        "id": "db",
                        "title": "DB",
                        "description": "实现数据库",
                        "priority": 2,
                        "depends_on": [],
                        "requirement_text": "实现数据库",
                    },
                ]
            },
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                f"""
runtimes:
  Splitter:
    cli: mock
    response: '{splitter_response}'
  Mock:
    cli: mock
    response: "done"
agents:
  - name: solution-architect
    runtime_id: Splitter
    role: architect
    prompt: agents/solution-architect.md
  - name: dev
    runtime_id: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: tech-lead-output.md
runner:
  auto_split_requirements: true
  context_threshold_chars: 10
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            for name in ["solution-architect", "dev"]:
                (root / ".ai" / "agents" / f"{name}.md").write_text(f"You are {name}.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("x" * 30, yes=True)

            self.assertEqual(report.status, "completed")
            self.assertEqual([unit.unit_id for unit in report.units], ["db", "api"])
            self.assertTrue((Path(report.output_dir) / "requirement-units" / "db" / "tech-lead-output.md").exists())
            self.assertTrue((Path(report.output_dir) / "requirement-units" / "api" / "tech-lead-output.md").exists())

    def test_save_checkpoint_writes_unit_progress(self) -> None:
        """checkpoint 支持 mode 与单元级进度，供 D3 resume 精确定位"""
        from engine.models import RequirementUnitProgress

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text("runtimes: {}\nagents: []\npipeline: []\n", encoding="utf-8")
            output_dir = root / ".ai" / "team-output" / "run-1"
            output_dir.mkdir(parents=True)
            orchestrator = Orchestrator(root, config_path=str(root / "test-config.yaml"))

            orchestrator._save_checkpoint(
                output_dir,
                "run-1",
                ["develop"],
                None,
                mode="multi-unit",
                units=[
                    RequirementUnitProgress(unit_id="unit-1", status="completed", completed_stages=["develop"]),
                    RequirementUnitProgress(unit_id="unit-2", status="in_progress", completed_stages=[], current_stage="qa"),
                ],
            )

            data = json.loads((output_dir / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(data["mode"], "multi-unit")
            self.assertEqual(data["units"][1]["unit_id"], "unit-2")
            self.assertEqual(data["units"][1]["current_stage"], "qa")
