from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.config import load_config, resolve_prompt_path, agent_map
from engine.context_scanner import ContextScanner, is_sensitive_path
from engine.human_gate import normalize_decision
from engine.models import HumanDecision
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
            prompt = resolve_prompt_path(root, loaded.path, agents["coder"])
            self.assertIn("templates/agents/coder.md", str(prompt))

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
    allow_auto_approve: true
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

    def test_orchestrator_does_not_complete_when_pr_delivery_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, capture_output=True, check=True)
            (root / "README.md").write_text("init\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "branch", "-m", "main"], cwd=root, capture_output=True, check=False)

            (root / "test-config.yaml").write_text(
                """
runtimes: {}
agents: []
pipeline:
  - id: develop
    name: Develop
    agents: []
worktree:
  enabled: true
  base_branch: main
  auto_cleanup: false
ci_cd:
  create_pr: true
""",
                encoding="utf-8",
            )

            with patch.object(Orchestrator, "_deliver_pr", return_value={"status": "failed", "error": "pr create failed"}):
                report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("ship it", yes=True)

            self.assertEqual(report.status, "failed")
            self.assertEqual(report.error_message, "pr create failed")
            self.assertEqual(report.pr_info["status"], "failed")

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
    allow_auto_approve: true
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("implement feature", yes=True)
            self.assertEqual(report.status, "completed")

    def test_code_apply_stage_type_is_deprecated(self) -> None:
        """code_apply 不再作为独立开发阶段执行，避免和 develop 语义重复。"""
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
    allow_auto_approve: true
worktree:
  enabled: false
quality_gates: []
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            (root / ".ai" / "agents" / "dev.md").write_text("You are dev.", encoding="utf-8")
            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("create a file", yes=True)
            self.assertEqual(report.status, "failed")
            self.assertEqual(report.stages[-1].stage_id, "code_apply")
            self.assertIn("deprecated", report.stages[-1].error_message or "")
            self.assertFalse((root / "output.txt").exists())

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
    allow_auto_approve: true
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

    def test_human_review_yes_requires_explicit_auto_approve_opt_in(self) -> None:
        """普通 human_review 默认也不能被 --yes 自动通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes: {}
agents: []
pipeline:
  - id: accept
    name: Accept
    type: human_review
worktree:
  enabled: false
""",
                encoding="utf-8",
            )

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("manual decision", yes=True)

            self.assertEqual(report.status, "paused")
            self.assertEqual(report.stages[-1].stage_id, "accept")

    def test_skip_if_no_blocker_requires_explicit_auto_skip_opt_in(self) -> None:
        """skip_if_no_blocker 不能再默认自动跳过人工确认。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ai").mkdir()
            (root / "test-config.yaml").write_text(
                """
runtimes: {}
agents: []
pipeline:
  - id: plan_confirm
    name: Plan Confirm
    type: human_review
    skip_if_no_blocker: true
worktree:
  enabled: false
""",
                encoding="utf-8",
            )

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("manual decision")

            self.assertEqual(report.status, "failed")
            self.assertIn("allow_auto_skip", report.error_message or "")

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
    allow_auto_skip: true
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
    allow_auto_skip: true
    allow_auto_approve: true
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

            self.assertEqual(report.status, "paused")
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
    allow_auto_skip: true
    allow_auto_approve: true
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
            self.assertEqual(waiting.status, "paused")
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

    def test_multi_unit_runs_global_hard_gate_before_unit_development(self) -> None:
        """大需求拆分后仍必须先经过全局人工确认，不能直接进入单元开发。"""
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
                    }
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
  Req:
    cli: mock
    response: "final requirement"
  Dev:
    cli: mock
    response: "done"
agents:
  - name: solution-architect
    runtime_id: Splitter
    role: architect
    prompt: agents/solution-architect.md
  - name: req
    runtime_id: Req
    role: analyst
    prompt: agents/req.md
  - name: dev
    runtime_id: Dev
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: requirement_synthesis
    name: Requirement Synthesis
    agents: [req]
    input: requirement
    output:
      req: requirement-final.md
  - id: requirement_confirm
    name: Requirement Confirm
    type: human_review
    output_file: human-decision-requirement.md
    decision_file: human-decision-requirement.json
    allow_auto_approve: false
    requires_reason_on_reject: true
    reject_to: requirement_synthesis
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
            for name in ["solution-architect", "req", "dev"]:
                (root / ".ai" / "agents" / f"{name}.md").write_text(f"You are {name}.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("x" * 30, yes=True)

            self.assertEqual(report.status, "paused")
            self.assertEqual(report.mode, "multi-unit")
            self.assertEqual(report.stages[-1].stage_id, "requirement_confirm")
            self.assertFalse((Path(report.output_dir) / "requirement-units" / "unit-1" / "tech-lead-output.md").exists())

    def test_multi_unit_acceptance_reject_reruns_unit_stages_not_root_develop(self) -> None:
        """最终验收拒绝时，develop/qa/review 仍按单元目录回流，不能退化成根目录执行。"""
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
                    }
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
  - name: req
    runtime_id: Mock
    role: analyst
    prompt: agents/req.md
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
  - id: requirement_synthesis
    name: Requirement Synthesis
    agents: [req]
    input: requirement
    output:
      req: requirement-final.md
  - id: requirement_confirm
    name: Requirement Confirm
    type: human_review
    output_file: human-decision-requirement.md
    decision_file: human-decision-requirement.json
    allow_auto_approve: false
    requires_reason_on_reject: true
    reject_to: requirement_synthesis
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
  - id: acceptance_confirm
    name: Acceptance Confirm
    type: human_review
    output_file: human-decision-acceptance.md
    decision_file: human-decision-acceptance.json
    allow_auto_approve: false
    requires_reason_on_reject: true
    reject_to: develop
runner:
  auto_split_requirements: true
  context_threshold_chars: 10
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / ".ai" / "agents").mkdir()
            for name in ["solution-architect", "req", "dev", "qa", "reviewer"]:
                (root / ".ai" / "agents" / f"{name}.md").write_text(f"You are {name}.", encoding="utf-8")

            first_wait = Orchestrator(root, config_path=str(root / "test-config.yaml")).run("x" * 30, run_id="multi-unit-acceptance")
            self.assertEqual(first_wait.status, "paused")
            self.assertEqual(first_wait.stages[-1].stage_id, "requirement_confirm")

            approved_requirement = HumanDecision(stage_id="requirement_confirm", decision="approved", reason="需求确认")
            acceptance_wait = Orchestrator(root, config_path=str(root / "test-config.yaml")).run(
                "x" * 30,
                run_id="multi-unit-acceptance",
                resume=True,
                human_decision=approved_requirement,
            )
            self.assertEqual(acceptance_wait.status, "paused")
            self.assertEqual(acceptance_wait.stages[-1].stage_id, "acceptance_confirm")

            rejected_acceptance = HumanDecision(
                stage_id="acceptance_confirm",
                decision="rejected",
                reason="验收未通过",
                required_changes=["补充登录失败提示"],
                target_stage="develop",
            )
            waiting_again = Orchestrator(root, config_path=str(root / "test-config.yaml")).run(
                "x" * 30,
                run_id="multi-unit-acceptance",
                resume=True,
                human_decision=rejected_acceptance,
            )

            output_dir = Path(waiting_again.output_dir)
            self.assertEqual(waiting_again.status, "paused")
            self.assertEqual(waiting_again.stages[-1].stage_id, "acceptance_confirm")
            self.assertTrue((output_dir / "requirement-units" / "unit-1" / "tech-lead-output.md").exists())
            self.assertFalse((output_dir / "tech-lead-output.md").exists())
            self.assertEqual([stage.stage_id for stage in waiting_again.stages].count("acceptance_confirm"), 2)

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


class TestHardHumanGateWorkflow(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        config = root / "team.yaml"
        config.write_text(
            """
runtimes:
  Req:
    cli: mock
    response: "final requirement"
  Plan:
    cli: mock
    response: "task plan"
agents:
  - name: req
    runtime_id: Req
    role: analyst
    prompt: agents/req.md
  - name: planner
    runtime_id: Plan
    role: planner
    prompt: agents/planner.md
pipeline:
  - id: requirement_synthesis
    name: Requirement Synthesis
    agents: [req]
    input: requirement
    output:
      req: requirement-final.md
  - id: requirement_confirm
    name: Requirement Confirm
    type: human_review
    output_file: human-decision-requirement.md
    decision_file: human-decision-requirement.json
    allow_auto_approve: false
    requires_reason_on_reject: true
    reject_to: requirement_synthesis
  - id: planning
    name: Planning
    agents: [planner]
    input: [requirement-final.md, human-decision-requirement.json]
    output:
      planner: task-plan.md
worktree:
  enabled: false
""",
            encoding="utf-8",
        )
        (root / "agents").mkdir()
        (root / "agents" / "req.md").write_text("You finalize requirements.", encoding="utf-8")
        (root / "agents" / "planner.md").write_text("You plan tasks.", encoding="utf-8")
        return config

    def test_hard_human_gate_waits_even_when_yes_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)

            report = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-waits", yes=True)

            self.assertEqual(report.status, "paused")
            gate = report.stages[-1]
            self.assertEqual(gate.stage_id, "requirement_confirm")
            self.assertEqual(gate.status, "waiting")
            output_dir = Path(report.output_dir)
            self.assertTrue((output_dir / "checkpoint.json").exists())
            decision = json.loads((output_dir / "human-decision-requirement.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "waiting")

    def test_reject_decision_requires_reason_and_loops_back_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-reject")
            self.assertEqual(waiting.status, "paused")

            decision = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="需求没有说明登录失败提示",
                required_changes=["补充登录失败提示验收标准"],
                target_stage="requirement_synthesis",
            )
            resumed = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-reject",
                resume=True,
                human_decision=decision,
            )

            self.assertEqual(resumed.status, "paused")
            stage_ids = [stage.stage_id for stage in resumed.stages]
            self.assertGreaterEqual(stage_ids.count("requirement_synthesis"), 2)
            feedback = Path(resumed.output_dir) / "human-feedback-requirement_confirm-1.md"
            self.assertTrue(feedback.exists())
            self.assertIn("需求没有说明登录失败提示", feedback.read_text(encoding="utf-8"))

    def test_reject_decision_target_must_match_stage_reject_to(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-invalid-target")
            self.assertEqual(waiting.status, "paused")

            decision = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="需求没有说明登录失败提示",
                target_stage="planning",
            )
            resumed = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-invalid-target",
                resume=True,
                human_decision=decision,
            )

            self.assertEqual(resumed.status, "failed")
            self.assertEqual(resumed.stages[-1].stage_id, "requirement_confirm")
            self.assertEqual(resumed.stages[-1].status, "failed")
            self.assertIn("target_stage", resumed.stages[-1].error_message or "")
            self.assertIn("reject_to", resumed.stages[-1].error_message or "")
            self.assertNotIn("planning", [stage.stage_id for stage in resumed.stages])

    def test_normalize_decision_does_not_mutate_input(self) -> None:
        stage = {"id": "requirement_confirm", "type": "human_review", "reject_to": "requirement_synthesis"}
        original = HumanDecision(
            stage_id="requirement_confirm",
            decision="rejected",
            reason="需求没有说明登录失败提示",
            required_changes=["补充登录失败提示验收标准"],
        )

        normalized = normalize_decision(stage, original)
        original.required_changes.append("补充账号锁定提示")

        self.assertEqual(normalized.target_stage, "requirement_synthesis")
        self.assertIsNone(original.target_stage)
        self.assertEqual(normalized.required_changes, ["补充登录失败提示验收标准"])
        self.assertIsNot(normalized.required_changes, original.required_changes)

    def test_multiple_rejects_keep_distinct_feedback_and_decision_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-multi-reject")
            self.assertEqual(waiting.status, "paused")

            first = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="第一次拒绝：缺少登录失败提示",
                required_changes=["补充登录失败提示"],
                target_stage="requirement_synthesis",
            )
            waiting_again = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-multi-reject",
                resume=True,
                human_decision=first,
            )
            self.assertEqual(waiting_again.status, "paused")

            second = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="第二次拒绝：缺少账号锁定提示",
                required_changes=["补充账号锁定提示"],
                target_stage="requirement_synthesis",
            )
            waiting_third = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-multi-reject",
                resume=True,
                human_decision=second,
            )

            self.assertEqual(waiting_third.status, "paused")
            output_dir = Path(waiting_third.output_dir)
            self.assertEqual(
                [item.reason for item in waiting_third.human_decisions],
                ["第一次拒绝：缺少登录失败提示", "第二次拒绝：缺少账号锁定提示"],
            )
            checkpoint = json.loads((output_dir / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [item["reason"] for item in checkpoint["human_decisions"]],
                ["第一次拒绝：缺少登录失败提示", "第二次拒绝：缺少账号锁定提示"],
            )

            feedback_files = sorted(output_dir.glob("human-feedback-requirement_confirm-*.md"))
            self.assertGreaterEqual(len(feedback_files), 2)
            feedback_contents = [path.read_text(encoding="utf-8") for path in feedback_files]
            self.assertTrue(any("第一次拒绝：缺少登录失败提示" in content for content in feedback_contents))
            self.assertTrue(any("第二次拒绝：缺少账号锁定提示" in content for content in feedback_contents))

            history_files = sorted(output_dir.glob("human-decision-requirement-*.json"))
            self.assertGreaterEqual(len(history_files), 2)
            history_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in history_files]
            rejected_reasons = [item.get("reason") for item in history_payloads if item.get("decision") == "rejected"]
            self.assertIn("第一次拒绝：缺少登录失败提示", rejected_reasons)
            self.assertIn("第二次拒绝：缺少账号锁定提示", rejected_reasons)

    def test_malformed_checkpoint_human_decisions_are_skipped_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-malformed-history")
            self.assertEqual(waiting.status, "paused")
            checkpoint_path = Path(waiting.output_dir) / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["human_decisions"] = [
                {"stage_id": "requirement_confirm", "decision": "approved", "reason": "old ok"},
                {"stage_id": "requirement_confirm", "decision": "invalid"},
                "not-a-dict",
            ]
            checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")

            approved = HumanDecision(stage_id="requirement_confirm", decision="approved", reason="继续")
            report = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-malformed-history",
                resume=True,
                human_decision=approved,
            )

            self.assertEqual(report.status, "completed")
            self.assertIn("planning", [stage.stage_id for stage in report.stages])
            warning_text = "\n".join(report.warnings)
            self.assertIn("checkpoint", warning_text)
            self.assertIn("human_decisions", warning_text)
            self.assertEqual([item.decision for item in report.human_decisions], ["approved", "approved"])

    def test_reject_decision_does_not_save_gate_completed_before_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-checkpoint-order")
            self.assertEqual(waiting.status, "paused")
            snapshots = []
            original_save_checkpoint = Orchestrator._save_checkpoint

            def capture_save_checkpoint(self, output_dir, run_id, completed_stages, worktree_path, **kwargs):
                snapshots.append(list(completed_stages))
                return original_save_checkpoint(self, output_dir, run_id, completed_stages, worktree_path, **kwargs)

            decision = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="需求没有说明登录失败提示",
                target_stage="requirement_synthesis",
            )
            with patch.object(Orchestrator, "_save_checkpoint", new=capture_save_checkpoint):
                resumed = Orchestrator(root, config_path=str(config)).run(
                    "ship auth",
                    run_id="gate-checkpoint-order",
                    resume=True,
                    human_decision=decision,
                )

            self.assertEqual(resumed.status, "paused")
            self.assertTrue(snapshots)
            self.assertFalse(any("requirement_confirm" in snapshot for snapshot in snapshots))

    def test_resume_preserves_human_decision_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            waiting = Orchestrator(root, config_path=str(config)).run("ship auth", run_id="gate-history")
            self.assertEqual(waiting.status, "paused")

            rejected = HumanDecision(
                stage_id="requirement_confirm",
                decision="rejected",
                reason="需求没有说明登录失败提示",
                required_changes=["补充登录失败提示验收标准"],
                target_stage="requirement_synthesis",
            )
            waiting_again = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-history",
                resume=True,
                human_decision=rejected,
            )
            self.assertEqual(waiting_again.status, "paused")
            self.assertEqual([item.decision for item in waiting_again.human_decisions], ["rejected"])
            checkpoint = json.loads((Path(waiting_again.output_dir) / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual([item["decision"] for item in checkpoint["human_decisions"]], ["rejected"])

            approved = HumanDecision(stage_id="requirement_confirm", decision="approved", reason="已补充")
            completed = Orchestrator(root, config_path=str(config)).run(
                "ship auth",
                run_id="gate-history",
                resume=True,
                human_decision=approved,
            )

            self.assertEqual(completed.status, "completed")
            self.assertIn("planning", [stage.stage_id for stage in completed.stages])
            self.assertEqual([item.decision for item in completed.human_decisions], ["rejected", "approved"])

    def test_only_stage_is_rejected_when_pipeline_has_hard_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)

            report = Orchestrator(root, config_path=str(config)).run("ship auth", only_stage="planning")

            self.assertEqual(report.status, "failed")
            self.assertIn("only_stage", report.error_message or "")
            self.assertIn("hard human gates", report.error_message or "")

    def test_skip_hard_gate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)

            report = Orchestrator(root, config_path=str(config)).run("ship auth", skip_stages=["requirement_confirm"])

            self.assertEqual(report.status, "failed")
            self.assertIn("skip_stages", report.error_message or "")
            self.assertIn("requirement_confirm", report.error_message or "")


class TestArtifactContractsAndStageContext(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)

    def _create_develop_feature_repo(self, root: Path, feature_line: str = "configured base change") -> None:
        self._git(root, "init")
        self._git(root, "config", "user.name", "Test User")
        self._git(root, "config", "user.email", "test@example.com")
        (root / "app.txt").write_text("baseline\n", encoding="utf-8")
        self._git(root, "add", "app.txt")
        self._git(root, "commit", "-m", "baseline")
        self._git(root, "branch", "-M", "develop")
        self._git(root, "checkout", "-b", "feature")
        (root / "app.txt").write_text(f"baseline\n{feature_line}\n", encoding="utf-8")
        self._git(root, "add", "app.txt")
        self._git(root, "commit", "-m", "feature change")

    def _create_large_diff_repo(self, root: Path) -> None:
        self._git(root, "init")
        self._git(root, "config", "user.name", "Test User")
        self._git(root, "config", "user.email", "test@example.com")
        (root / "base.txt").write_text("baseline\n", encoding="utf-8")
        self._git(root, "add", "base.txt")
        self._git(root, "commit", "-m", "baseline")
        self._git(root, "branch", "-M", "main")
        self._git(root, "checkout", "-b", "feature")
        (root / "committed.txt").write_text("committed diff\n" + ("C" * 800) + "\n", encoding="utf-8")
        self._git(root, "add", "committed.txt")
        self._git(root, "commit", "-m", "committed change")
        (root / "staged.txt").write_text("staged diff\n" + ("S" * 800) + "\n", encoding="utf-8")
        self._git(root, "add", "staged.txt")
        (root / "unstaged.txt").write_text("unstaged diff\n" + ("U" * 800) + "\n", encoding="utf-8")

    def test_required_artifact_missing_blocks_next_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "plain text without required json"
agents:
  - name: req
    runtime_id: Mock
    prompt: agents/req.md
pipeline:
  - id: requirement_synthesis
    agents: [req]
    input: requirement
    output:
      req: requirement-final.md
    required_artifacts:
      - requirement-final.json
  - id: planning
    agents: [req]
    input: [requirement-final.json]
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "req.md").write_text("You write output.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("req")

            self.assertEqual(report.status, "failed")
            self.assertIn("required artifact missing", report.error_message)
            self.assertTrue(report.stages[0].artifact_validations)
            self.assertNotIn("planning", [stage.stage_id for stage in report.stages])

    def test_context_scan_writes_markdown_and_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                """
runtimes: {}
agents: []
pipeline:
  - id: context_scan
    name: Context Scan
    type: context_scan
    output_file: codebase-context.md
    output_json: codebase-context.json
    required_artifacts:
      - codebase-context.md
      - codebase-context.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "app.py").write_text("print('hi')\n", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("scan")

            self.assertEqual(report.status, "completed")
            output_dir = Path(report.output_dir)
            self.assertTrue((output_dir / "codebase-context.md").exists())
            payload = json.loads((output_dir / "codebase-context.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["project_root"], str(root.resolve()))
            self.assertIn("project_types", payload)
            self.assertIn("tree", payload)
            self.assertEqual(report.stages[0].artifact_validations[-1].status, "passed")

    def test_stage_json_artifacts_name_multiple_json_blocks_by_contract(self) -> None:
        response = """# Plan

```json
{"status": "completed", "summary": "solution", "decisions": [], "alternatives_considered": [], "impact_scope": [], "configuration_strategy": {}, "risks": [], "rollback_strategy": {}, "verification_strategy": [], "evidence": [], "next_stage_contract": {}}
```

```json
{"status": "completed", "summary": "tasks", "tasks": [{"id": "task-001", "title": "t", "description": "d", "priority": "P0", "acceptance_criteria_refs": ["AC-001"]}], "execution_order": [["task-001"]], "file_boundaries": [], "test_plan": [], "rollback_considerations": [], "acceptance_coverage": [], "evidence": [], "next_stage_contract": {}}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: planner
    runtime_id: Mock
    prompt: agents/planner.md
pipeline:
  - id: planning
    agents: [planner]
    input: requirement
    output:
      planner: task-plan.md
    json_artifacts:
      - solution-plan.json
      - task-plan.json
    required_artifacts:
      - solution-plan.json
      - task-plan.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "planner.md").write_text("Plan the work.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "completed")
            output_dir = Path(report.output_dir)
            solution = json.loads((output_dir / "solution-plan.json").read_text(encoding="utf-8"))
            task_plan = json.loads((output_dir / "task-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(solution["summary"], "solution")
            self.assertEqual(task_plan["summary"], "tasks")
            self.assertFalse((output_dir / "task-plan-1.json").exists())
            self.assertFalse((output_dir / "task-plan-2.json").exists())

    def test_artifact_contract_validates_named_required_fields(self) -> None:
        response = """# Plan

```json
{"status": "completed", "summary": "solution", "decisions": [], "alternatives_considered": [], "impact_scope": [], "configuration_strategy": {}, "risks": [], "rollback_strategy": {}, "verification_strategy": [], "evidence": [], "next_stage_contract": {}}
```

```json
{"status": "completed", "summary": "tasks", "tasks": []}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: planner
    runtime_id: Mock
    prompt: agents/planner.md
pipeline:
  - id: planning
    agents: [planner]
    input: requirement
    output:
      planner: task-plan.md
    json_artifacts:
      - solution-plan.json
      - task-plan.json
    required_artifacts:
      - solution-plan.json
      - task-plan.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "planner.md").write_text("Plan the work.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "failed")
            self.assertIn("task-plan.json", report.error_message or "")
            self.assertTrue(
                "execution_order" in (report.error_message or "") or "tasks" in (report.error_message or ""),
                f"Expected schema validation error, got: {report.error_message}",
            )

    def test_stage_json_artifacts_rejects_parent_directory_path(self) -> None:
        response = """# Plan

```json
{"status": "completed", "summary": "outside"}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside_path = root / ".ai" / "team-output" / "outside.json"
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: planner
    runtime_id: Mock
    prompt: agents/planner.md
pipeline:
  - id: planning
    agents: [planner]
    input: requirement
    output:
      planner: task-plan.md
    json_artifacts:
      - ../outside.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "planner.md").write_text("Plan the work.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "failed")
            self.assertIn("json_artifacts", report.error_message)
            self.assertTrue("invalid json_artifacts path" in report.error_message or "outside output dir" in report.error_message)
            self.assertFalse(outside_path.exists())

    def test_stage_json_artifacts_rejects_absolute_path(self) -> None:
        response = """# Plan

```json
{"status": "completed", "summary": "absolute outside"}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside_path = root / "outside-absolute.json"
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: planner
    runtime_id: Mock
    prompt: agents/planner.md
pipeline:
  - id: planning
    agents: [planner]
    input: requirement
    output:
      planner: task-plan.md
    json_artifacts:
      - {outside_path}
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "planner.md").write_text("Plan the work.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "failed")
            self.assertIn("json_artifacts", report.error_message)
            self.assertTrue("invalid json_artifacts path" in report.error_message or "outside output dir" in report.error_message)
            self.assertFalse(outside_path.exists())

    def test_stage_json_artifacts_rejects_multi_agent_stage(self) -> None:
        response = """# Plan

```json
{"status": "completed", "summary": "shared artifact"}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: planner
    runtime_id: Mock
    prompt: agents/planner.md
  - name: reviewer
    runtime_id: Mock
    prompt: agents/reviewer.md
pipeline:
  - id: planning
    agents: [planner, reviewer]
    input: requirement
    output:
      planner: planner-output.md
      reviewer: reviewer-output.md
    json_artifacts:
      - task-plan.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "planner.md").write_text("Plan the work.", encoding="utf-8")
            (root / "agents" / "reviewer.md").write_text("Review the work.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "failed")
            self.assertIn("json_artifacts", report.error_message)
            self.assertIn("single-agent", report.error_message)

    def test_stage_without_json_artifacts_uses_legacy_numbered_names_for_multiple_json_blocks(self) -> None:
        response = """# Legacy Output

```json
{"status": "completed", "summary": "first", "kind": "first", "value": 1}
```

```json
{"status": "completed", "summary": "second", "kind": "second", "value": 2}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: legacy
    runtime_id: Mock
    prompt: agents/legacy.md
pipeline:
  - id: legacy_stage
    agents: [legacy]
    input: requirement
    output:
      legacy: legacy-output.md
    required_artifacts:
      - legacy-output-1.json
      - legacy-output-2.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "legacy.md").write_text("Write legacy output.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "completed")
            output_dir = Path(report.output_dir)
            first = json.loads((output_dir / "legacy-output-1.json").read_text(encoding="utf-8"))
            second = json.loads((output_dir / "legacy-output-2.json").read_text(encoding="utf-8"))
            self.assertEqual(first, {"status": "completed", "summary": "first", "kind": "first", "value": 1})
            self.assertEqual(second, {"status": "completed", "summary": "second", "kind": "second", "value": 2})
            self.assertFalse((output_dir / "legacy-output.json").exists())

    def test_stage_without_json_artifacts_uses_legacy_stem_name_for_single_json_block(self) -> None:
        response = """# Legacy Output

```json
{"status": "completed", "summary": "single", "kind": "single", "value": 1}
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team.yaml").write_text(
                f"""
runtimes:
  Mock:
    cli: mock
    response: {json.dumps(response)}
agents:
  - name: legacy
    runtime_id: Mock
    prompt: agents/legacy.md
pipeline:
  - id: legacy_stage
    agents: [legacy]
    input: requirement
    output:
      legacy: legacy-output.md
    required_artifacts:
      - legacy-output.json
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "legacy.md").write_text("Write legacy output.", encoding="utf-8")

            report = Orchestrator(root, config_path=str(root / "team.yaml")).run("ship it")

            self.assertEqual(report.status, "completed")
            output_dir = Path(report.output_dir)
            artifact = json.loads((output_dir / "legacy-output.json").read_text(encoding="utf-8"))
            self.assertEqual(artifact, {"status": "completed", "summary": "single", "kind": "single", "value": 1})
            self.assertFalse((output_dir / "legacy-output-1.json").exists())

    def test_stage_context_includes_contract_and_confirmed_artifacts(self) -> None:
        from engine.stage_context import build_stage_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / "requirement-final.json").write_text('{"status":"completed","summary":"req"}', encoding="utf-8")
            (output_dir / "task-plan.json").write_text('{"status":"completed","summary":"plan"}', encoding="utf-8")

            context = build_stage_context(
                stage={"id": "develop", "name": "开发实施", "required_artifacts": ["implementation-report.json"]},
                output_dir=output_dir,
                cwd=root,
                input_items=["requirement-final.json", "task-plan.json"],
                extra_feedback="人工拒绝反馈",
                schema_hint={"required": ["status", "summary"]},
            )

            self.assertIn("## Stage Contract", context)
            self.assertIn("implementation-report.json", context)
            self.assertIn("人工拒绝反馈", context)
            self.assertIn("Artifact: `requirement-final.json`", context)
            self.assertIn('"summary":"req"', context)
            self.assertIn('"summary":"plan"', context)

    def test_stage_context_git_diff_includes_staged_changes(self) -> None:
        from engine.stage_context import build_stage_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            self._git(root, "init")
            self._git(root, "config", "user.name", "Test User")
            self._git(root, "config", "user.email", "test@example.com")
            (root / "app.txt").write_text("baseline\n", encoding="utf-8")
            self._git(root, "add", "app.txt")
            self._git(root, "commit", "-m", "baseline")
            (root / "app.txt").write_text("baseline\nstaged change\n", encoding="utf-8")
            self._git(root, "add", "app.txt")

            context = build_stage_context(
                stage={"id": "review", "name": "Review"},
                output_dir=output_dir,
                cwd=root,
                input_items=["git-diff"],
            )

            self.assertIn("+staged change", context)
            self.assertNotIn("(no diff)", context)

    def test_stage_context_git_diff_includes_committed_branch_changes(self) -> None:
        from engine.stage_context import build_stage_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            self._git(root, "init")
            self._git(root, "config", "user.name", "Test User")
            self._git(root, "config", "user.email", "test@example.com")
            (root / "app.txt").write_text("baseline\n", encoding="utf-8")
            self._git(root, "add", "app.txt")
            self._git(root, "commit", "-m", "baseline")
            self._git(root, "branch", "-M", "main")
            self._git(root, "checkout", "-b", "feature")
            (root / "app.txt").write_text("baseline\ncommitted change\n", encoding="utf-8")
            self._git(root, "add", "app.txt")
            self._git(root, "commit", "-m", "feature change")

            context = build_stage_context(
                stage={"id": "review", "name": "Review"},
                output_dir=output_dir,
                cwd=root,
                input_items=["git-diff"],
            )

            self.assertIn("+committed change", context)
            self.assertNotIn("(no diff)", context)

    def test_stage_context_git_diff_uses_configured_base_branch(self) -> None:
        from engine.stage_context import build_stage_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            self._create_develop_feature_repo(root)

            context = build_stage_context(
                stage={"id": "review", "name": "Review"},
                output_dir=output_dir,
                cwd=root,
                input_items=["git-diff"],
                base_branch="develop",
            )

            self.assertIn("+configured base change", context)
            self.assertNotIn("(no diff)", context)

    def test_render_prompt_passes_configured_base_branch_to_stage_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_develop_feature_repo(root, feature_line="prompt configured base change")
            (root / "team.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "ok"
agents:
  - name: reviewer
    runtime_id: Mock
    prompt: agents/reviewer.md
pipeline:
  - id: review
    agents: [reviewer]
    input: [git-diff]
worktree:
  enabled: false
  base_branch: develop
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "reviewer.md").write_text("Review changes.", encoding="utf-8")
            output_dir = root / "out"
            output_dir.mkdir()
            orchestrator = Orchestrator(root, config_path=str(root / "team.yaml"))

            prompt = orchestrator._render_prompt(
                stage={"id": "review", "name": "Review", "input": ["git-diff"]},
                agent=orchestrator.agents["reviewer"],
                output_dir=output_dir,
                cwd=root,
            )

            self.assertIn("+prompt configured base change", prompt)
            self.assertNotIn("(no diff)", prompt)

    def test_stage_context_truncates_large_git_diff(self) -> None:
        from engine.stage_context import build_stage_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            self._create_large_diff_repo(root)

            context = build_stage_context(
                stage={"id": "review", "name": "Review"},
                output_dir=output_dir,
                cwd=root,
                input_items=["git-diff"],
                max_diff_chars=200,
            )

            self.assertIn("[git-diff truncated, original chars:", context)
            self.assertIn("limit: 200", context)
            self.assertLess(len(context), 900)

    def test_render_prompt_passes_max_input_chars_to_git_diff_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_large_diff_repo(root)
            (root / "team.yaml").write_text(
                """
runtimes:
  Mock:
    cli: mock
    response: "ok"
agents:
  - name: reviewer
    runtime_id: Mock
    prompt: agents/reviewer.md
pipeline:
  - id: review
    agents: [reviewer]
    input: [git-diff]
runner:
  max_input_chars_per_file: 200
worktree:
  enabled: false
""",
                encoding="utf-8",
            )
            (root / "agents").mkdir()
            (root / "agents" / "reviewer.md").write_text("Review changes.", encoding="utf-8")
            output_dir = root / "out"
            output_dir.mkdir()
            orchestrator = Orchestrator(root, config_path=str(root / "team.yaml"))

            prompt = orchestrator._render_prompt(
                stage={"id": "review", "name": "Review", "input": ["git-diff"]},
                agent=orchestrator.agents["reviewer"],
                output_dir=output_dir,
                cwd=root,
            )

            self.assertIn("[git-diff truncated, original chars:", prompt)
            self.assertIn("limit: 200", prompt)
