# 知网主题文献助手 · cnki-topic-library

给Agent一个研究主题，让它自动检索知网、阅读摘要、筛选相关与热门文献，并使用你的机构权限下载论文。

面向 **Windows 上的 DeepSeek Harness（DSH）和Codex**。下载篇数自由指定，未指定默认100篇；支持中途调整目标、失败补位、去重、文件核验和断点续跑。Skill使用宿主Agent理解需求，无需额外的模型API密钥；本地任务工具仅依赖Python 3.10+标准库。安装说明与自动检查均以Windows为支持范围。

## 安装到DeepSeek Harness

在Windows PowerShell中运行，需要已安装Git和Python 3.10+：

```powershell
git clone https://github.com/MG-521-LY/cnki-topic-library.git
cd cnki-topic-library
python scripts/install.py --client dsh
```

如果Windows上使用Python启动器，将上述 `python` 替换为 `py -3`。也可使用DSH已提供的Python 3.10+解释器的实际路径。

安装脚本会把完整目录包放到 `$env:DSH_HOME\skills\cnki-topic-library`，未设置 `DSH_HOME` 时使用 `$env:USERPROFILE\.dsh\skills\cnki-topic-library`。不写入模型密钥，不修改DSH插件配置。

只在某个项目使用：

```powershell
python scripts/install.py --client dsh --project "D:\Projects\my-research"
```

更新：

```powershell
git pull --ff-only
python scripts/install.py --client dsh --force
```

`--force`会先把已有Skill完整备份到技能根目录的 `.backups/` 下，再安装新版。指定自定义技能根目录用 `--dest`；只预览不写文件用 `--dry-run`。安装时保留目录的单层结构，入口应是 `<技能根>/cnki-topic-library/SKILL.md`。

## 在DSH中使用

用户可直接调用：

```text
/cnki-topic-library 搜集“生成式人工智能对大学生自主学习的影响”的相关文献，成功下载5篇PDF，相关性优先，兼顾热度。
```

也可以自然语言要求“使用 cnki-topic-library”。模型应通过宿主的 `skill` 工具加载完整说明后执行。同一主题下只发“30”表示把总目标改为30篇；“再下载20篇”表示追加20篇；年份与“近5年”不作为篇数。

### 宿主需要的能力

1. Skill发现和加载：`dsh-skill`、`dsh-skill-filesystem`、`dsh-tool-skill`或等效组合。
2. 能操作本机校园网浏览器并保存文件的浏览器后端。
3. 本地文件和命令执行能力，以及Python 3.10+。

DSH版本和profile不同，浏览器工具名、参数及是否启用可能不同。该Skill不硬编码Codex的浏览器API，也不自动安装或修改浏览器提供方。安装成功后若没有浏览器能力，仍不能执行真实下载；DSH应指出缺失能力，按该版本官方文档配置后再执行。

详情：[DSH适配说明](skills/cnki-topic-library/references/deepseek-harness.md)；[浏览器流程](skills/cnki-topic-library/references/browser-workflow.md)。

## 安装到Codex

```powershell
python scripts/install.py --client codex
```

安装到 `$env:CODEX_HOME\skills\cnki-topic-library`，未设置时使用 `$env:USERPROFILE\.codex\skills\cnki-topic-library`。通过 `$cnki-topic-library` 调用。

也可使用Codex的skill-installer按GitHub仓库路径 `skills/cnki-topic-library` 安装。

## 下载结果

每个任务保存在工作区 `outputs/` 下，包含：

- `papers/`：实际下载的PDF。
- `task/library.csv`：题录、作者、年份、来源、热度、筛选理由、状态及文件位置。
- `task/report.md`：检索范围、筛选策略、成功数和失败原因。
- `task/manifest.json`、`task/task.json`：任务记录及恢复状态。

成功计数以实际核验文件为准；点击按钮或拿到链接不算成功。学校权限仍决定下载范围。遇到可见验证码、限流或登录失效，暂停并由用户在浏览器内处理。默认只接受真实PDF，用户明确接受时可启用CAJ。

## 验证

```text
python -m unittest discover -s tests -v
python skills/cnki-topic-library/tests/test_library_jobs.py
```

任务工具测试使用临时题录与生成的PDF，不连接知网，不动浏览器。安装测试使用临时技能目录。

- 已在Codex校园网浏览器上完成一次真实5篇测试：采集30个候选、阅读8篇摘要、下载5篇不同PDF并核验，达到目标即停止。
- 已用本机DeepSeek Harness 0.2.0-rc.2的实际文件系统Skill提供方验证目录发现、完整说明加载及相对资源基目录。
- 尚未完成DSH中的真实文献下载和真实100篇任务，也不承诺所有机构入口都能直接适配。

热度排名仅限本次候选样本，不能称为知网全库最热门，也不等同论文质量。筛选分值是可调策略。文件签名/大小/结束标记/哈希是初筛，需要时由宿主再用PDF解析和渲染工具检查。

## 目录

```text
skills/cnki-topic-library/  Skill入口、执行规则、任务脚本和测试
scripts/install.py         DSH/Codex安装器（Windows支持）
tests/test_install.py      安装器测试
.github/workflows/test.yml  Windows、Python 3.10/3.12测试
```

MIT许可证。仓库分发代码和Skill，不包含校园网认证信息或下载的论文全文。
