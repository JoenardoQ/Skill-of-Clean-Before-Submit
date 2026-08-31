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
3. 运行内置只读暂存内容扫描器及仓库已有检查，但不把扫描结果当作安全证明；
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
├── tests/
│   └── test_audit_staged.py
└── clean-before-commit/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/review-policy.md
    └── scripts/audit_staged.py
```

只有 `clean-before-commit/` 会被安装；测试和评估材料保留在运行时包之外。

## 安装

```bash
mkdir -p ~/.agents/skills
ln -s "/home/joenardo/My Projects/SKILL_Clean_Before_Commit/clean-before-commit" \
  ~/.agents/skills/clean-before-commit
```

替换前必须确认已有目标，避免同时存在源码链接和安装副本；必要时重启 Codex。

## 验证

```bash
python3 -B tests/test_audit_staged.py
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" \
  clean-before-commit
python3 "$HOME/My Projects/SKILL_Agent_Skill_Author/agent-skill-author/scripts/validate_skill.py" \
  clean-before-commit --policy release-policy.json
python3 "$HOME/My Projects/SKILL_Agent_Skill_Author/agent-skill-author/scripts/validate_eval_spec.py" \
  evaluation/eval-spec.json
```

## 验收与限制

验收条件包括：确定性只读扫描、脱敏诊断、明确授权门、最终索引复查、本地测试通过，
以及运行时包中没有开发残留。占位符豁免必须完整匹配有文档说明的合成值或环境变量
引用；凭据形态的值不能仅因包含 `example`、`dummy` 或 `redacted` 等单词而被视为
安全。测试必须覆盖扫描器的阻断、待审查、干净和错误退出，以及重要文件与信任边界。

模式扫描可能误报，也不能证明不存在密钥、废弃设计或隐藏的动态调用者。源码链接的
Skill 已安装到重命名后的目录；但在没有独立生命周期证据时，自动路由、入口加载、
完整行为评估、远端回读和恢复路径仍属于未验证项。
