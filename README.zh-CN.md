# 提交前清理

## 用途

`clean-before-commit` 是在 Git commit 或 push 前审查准确变更集的 Codex Skill。
它会在内容进入仓库历史或远端之前，识别密钥泄露、生产或个人数据、生成残留、废弃
脚手架、调试代码、过期 Fixture、大型或异常文件、无关改动，以及不必要的代码或
架构。

## 安全边界

Skill 默认只读。调用本身不授权删除、暂存、提交、推送、使用凭据或执行其他外部
写入。任何变更前都必须确定准确仓库、路径、Diff、目标分支和当前授权。含义不明确
或既有文件只报告并等待决定，不得直接删除。

诊断信息不得打印密钥值。如果真实凭据可能已经进入 Git 历史，仅删除本地文件并不
足够；Skill 必须阻止发布，并说明吊销凭据和修复历史需要分别决策。

## 工作流

Skill 将：

1. 确认仓库根目录、分支、上游、工作区状态、索引状态和准确的已暂存 Diff；
2. 盘点已暂存、未暂存、未跟踪、已忽略、二进制和大型文件；
3. 运行内置只读扫描器，盘点每种暂存变更状态，并以有界读取检查包含内容的暂存项和
   未跟踪项；不得跟随未跟踪符号链接，也不得把扫描结果当作安全证明；
4. 按证据分类阻断项、待确认项、无关工作和已验证的预期文件，并提出修复方案；
5. 只执行已获授权的清理，随后运行相关测试并通过明确路径重建索引；
6. 在任何单独授权的 commit 或 push 前重新审查最终暂存字节；push 后读取远端状态
   验证请求的版本。

## 架构

```text
SKILL_Clean_Before_Commit/
├── README.md
├── README.zh-CN.md
├── evaluation/
│   └── eval-spec.json
├── release-policy.json
├── tests/
│   └── test_audit_staged.py
└── clean-before-commit/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/review-policy.md
    └── scripts/audit_staged.py
```

只有 `clean-before-commit/` 会被安装；测试、评估计划和发布策略是运行时包之外的
维护者资源。生成的评估证据和项目历史记录仅保存在本地，并由 Git 忽略。

## 前置条件

- Git 2.x，并且本地仓库及索引可读。
- Python 3.10 或更高版本；扫描器仅使用标准库。
- 运行时使用需要 Codex 或其他能够发现 Agent Skill 的宿主；宿主发现和行为仍需独立
  验证。

## 安装

让 Codex 从 GitHub 下载 Skill：

```text
使用 $skill-installer 安装
https://github.com/JoenardoQ/Skill-of-Clean-Before-Submit/tree/main/clean-before-commit
```

安装后新建一个 Codex 任务。不要把已安装 Skill 链接到开发检出目录；需要更新时应从
GitHub 重新安装。

## 验证

在仓库根目录运行无第三方依赖的检查：

```bash
python3 -B tests/test_audit_staged.py
python3 "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" \
  clean-before-commit
```

拥有 Agent Skill Author 项目的维护者可使用以下命令运行发布策略与评估规格验证，且
无需假设固定检出位置：

```bash
export AGENT_SKILL_AUTHOR_ROOT=/path/to/SKILL_Agent_Skill_Author
python3 "$AGENT_SKILL_AUTHOR_ROOT/agent-skill-author/scripts/validate_skill.py" \
  clean-before-commit --policy release-policy.json
python3 "$AGENT_SKILL_AUTHOR_ROOT/agent-skill-author/scripts/validate_eval_spec.py" \
  evaluation/eval-spec.json
```

扫描器未发现项目时退出码为 `0`，产生一个或多个阻断项或待审查项时为 `1`，调用
参数无效或审查/Git 失败时为 `2`。JSON 输出保留 `repository`、`staged_files`、
`untracked_files`、`findings`、`summary` 和 `limitations`，并新增
`staged_changes`，其中包含状态、路径、适用时的原路径，以及新旧 Git 模式。

JSON 输出必须是有效 UTF-8。无法按 UTF-8 解码的文件系统字节及控制字符必须写为
JSON 转义序列，而不是原始字节；文本输出对路径和诊断信息采用相同安全边界。

## 验收与限制

验收条件包括：确定性只读扫描；盘点新增、Git 已识别的复制、删除、修改、重命名和类型
变化；有界读取内容；不跟随未跟踪符号链接；脱敏诊断；明确授权门；最终索引复查；
本地测试通过；以及运行时包中没有开发残留。占位符豁免必须完整匹配有文档说明的合成值或环境变量
引用；凭据形态的值不能仅因包含 `example`、`dummy` 或 `redacted` 等单词而被视为
安全。带引号的赋值必须按包含空格在内的完整值审查。测试必须把扫描器的阻断、待审查、
干净和错误退出追溯到重要 Git 状态、文件、资源与信任边界。

模式扫描可能误报，也不能证明不存在密钥、废弃设计或隐藏的动态调用者。未跟踪内容
只是工作区在扫描时的快照，之后仍可能变化；commit 前仍必须重新读取最终 Git 索引。
在没有独立生命周期证据时，自动路由、
入口加载、完整行为评估、远端回读和恢复路径仍属于未验证项。
