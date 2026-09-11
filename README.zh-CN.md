# 提交前清理

[English](README.md)

## 用途

在 commit 或 push 前审查准确的 Git 变更集。识别敏感内容、生成残留、废弃脚手架、调试残留、无关改动和不必要的代码或架构，同时保留必要行为。

这是一份供有仓库访问能力的 agent 使用的流程。内置扫描器辅助机械检查，不替代对架构或删除必要性的判断。

## 使用

阅读 `clean-before-commit/SKILL.md`，或通过所选宿主的 skill 机制安装完整的 `clean-before-commit/` 目录。可选的 `agents/openai.yaml` 提供 Codex 界面元数据。

```text
使用 $clean-before-commit 审查暂存改动。只报告问题。
```

```text
使用 $clean-before-commit 清理本次要求的改动，然后 commit 并 push
到已配置的上游。保留无关工作文件。
```

只审查时保持只读。已明确授予的清理、commit 和 push 权限在其范围内持续有效。所有权不明、目标变化、重写历史或凭据处置需要另行决定。

## 工作流程

1. 确认仓库、预期工作、变更集和授权。
2. commit 前检查索引及相关工作文件；push 前检查待推送提交。
3. 有条件时运行扫描器，并根据真实消费者和要求判断结果。
4. 只清理已核实且获授权的内容，运行受影响的检查。
5. 审查最终索引，按要求 commit，并在获授权的 push 后验证远端分支。

暂存区干净不代表待推送提交安全。后续提交删除的内容，仍可能存在于即将推送的历史中。

## 扫描器

需要 Git 和 Python 3.10 或更高版本，仅使用 Python 标准库。在仓库检出目录运行：

```bash
python3 clean-before-commit/scripts/audit_staged.py --repo /path/to/repository
python3 clean-before-commit/scripts/audit_staged.py --repo /path/to/repository --json
```

从其他位置运行时，以已安装 skill 的目录解析脚本路径。没有 Python 时使用等效只读工具，并明确未检查的内容。

| 退出码 | 含义 |
| --- | --- |
| 0 | 扫描器未发现问题 |
| 1 | 存在阻断项或待审查项，需要判断 |
| 2 | 调用或审查失败 |

扫描器盘点暂存改动与未跟踪文件，限制读取大小，不跟随未跟踪符号链接，并对疑似敏感值脱敏。它不检查全部未暂存内容、忽略文件或待推送历史。已核实为预期改动的待审查项不自动阻断；未解决的高影响内容会阻断。

JSON 包含 `repository`、`staged_files`、`staged_changes`、`untracked_files`、`findings`、`summary` 和 `limitations`。路径和诊断会转义不安全字符。模式扫描可能漏报或误报。

## 维护与验证

从仓库根目录运行现有扫描器测试：

```bash
python3 -B tests/test_audit_staged.py
git diff --check
```

同时检查 skill 引用，并验证指令改动涉及的决策：只读审查、已授权清理、有合理用途的扫描发现，以及推送已经形成的提交。

修改可执行行为时，同步维护扫描器及其测试。运行时目录包含入口、审查策略、扫描器和界面元数据。开发记录应放在运行时和正式文档之外。

不要输出疑似密钥值。已删除的凭据仍可能需要吊销和经授权的历史修复；一般清理请求不包含这两种授权。
