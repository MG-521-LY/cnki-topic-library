# DeepSeek Harness适配

## 加载与资源路径

本适配面向Windows。安装的是标准目录Skill，目录名 `cnki-topic-library`，入口 `SKILL.md`。默认用户安装位置为 `$env:DSH_HOME\skills\cnki-topic-library`，未设置该环境变量时为 `$env:USERPROFILE\.dsh\skills\cnki-topic-library`；项目安装位置为项目Git根目录下的 `.dsh/skills/cnki-topic-library`。不要把整个仓库套在该目录下，造成 `skills/cnki-topic-library/SKILL.md` 两层嵌套。

用户可输入 `/cnki-topic-library`，模型可使用宿主暴露的 `skill` 工具加载同名Skill。加载后的资源基目录用于定位这里的 `scripts/library_jobs.py` 和其他references；不要使用开发者的Windows路径或Codex安装目录。未发现该Skill时，检查实际配置的用户/项目/自定义根目录及Skill注册、文件提供方、加载工具是否已启用。

## 命令执行

优先用宿主的PowerShell工具（如 `pwsh`），以当前可见工具为准。先找Python 3.10+解释器，能用 `python` 或 `py -3` 就直接用。若DSH提供 `workspace_dependencies` 工具，可查询捆绑的Python路径；不要猜机器安装盘符。PowerShell调用含空格的解释器路径时使用调用运算符，例如 `& "C:\实际目录\python.exe" "D:\实际Skill路径\scripts\library_jobs.py" --help`。

命令中的脚本与任务路径用实际绝对路径并按shell正确引用。篇数由Agent根据上下文理解再传 `--count N`。帮助脚本只用标准库，不依赖额外模型接口。

## 浏览器能力

Skill加载不意味着具备浏览器操作。检查当前Session实际暴露的浏览器工具及文档；优先用已有、能走校园出口的浏览器。DSH的浏览器提供方可以是Playwright MCP、Chrome DevTools MCP或其他已连接的后端。不同后端的工具名和返回形状不同，按实际文档操作，不能调用Codex的 `cua` / `downloadMedia` 作为通用DSH API。

例如Playwright型工具应读取快照、观察定位器、填写检索框和点击，使用它实际支持的下载方法保存文件；Chrome DevTools型工具使用页面快照、页面操作和实际返回的下载路径。若当前后端只能访问网页但不能保存文件，就说明具体缺失能力，不能用下载链接代替文件。

需要启用浏览器提供方时，先检查所用DSH版本及profile/preset当前配置，再参考该版本官方文档。只挂载一个浏览器提供方，不覆盖用户已有插件设置或认证配置。安装本Skill的脚本不改DSH配置，不启用浏览器后端。

### 工具加载时机

Playwright MCP提供方加载或重新加载后，不会接管已经活动的Session。配置加载完成后，创建新会话，或卸载并恢复原会话，再检查工具目录。工具名通常为 `mcp__playwright-mcp__<tool>`，实际名称和参数以当前会话暴露的schema为准。外部脚本通过Playwright直连成功，只证明该连接可用，不能证明当前DSH会话已经获得这些工具。

新会话仍没有工具时，检查所选profile/preset、提供方加载和MCP启动日志，以及attach连接是否被其他会话占用；必要时重启DSH，再新建或恢复会话并核验。不能承诺重启必然修复依赖、配置或连接问题。工具缺失时先保存任务，不反复发起下载。

### 隔离浏览器与人工验证

当前官方Playwright MCP实现的launch模式使用 `--isolated`，每次新的浏览器运行状态不继承日常浏览器的登录配置；同一活动Session的轮次之间保留状态。用户2026-10-15反馈：全新配置首次检索可能遇到可见滑块，已使用过的配置能继续检索。这是该环境实测，不保证每次都会触发或已有配置永远免验证。

可见“请完成安全验证”或滑块实际阻挡操作时，按 [浏览器流程](browser-workflow.md) 保存进度、暂停并交给用户操作，不自动解题或尝试绕过。人工处理需要可见窗口；launch配置 `headless: false` 时窗口可供用户操作。若当前为无头模式，说明需要可见浏览器及会话重新初始化，保留任务后再处理，不能直接假设已出现窗口。不要为减少验证码而自动修改隔离模式或导入用户凭据。

机构认证依赖本机网络和当前浏览器会话。由DSH新建浏览器时，校园IP权限可能直接有效；学校代理/个人登录可能需要用户在浏览器中完成。恢复DSH会话后仍要核实浏览器身份，不能以日志中的旧身份作为当前权限证明。

## 验证和交付

执行 `python <实际Skill路径>/tests/test_library_jobs.py` 验证本地任务工具，再做一个5篇真实任务。测试目录放在任务工作区，不能放在安装目录内。真实下载与语义筛选的质量需要现场验证；当前Codex上的5篇成功记录不等于DSH已实测下载。

生成论文文件和CSV/Markdown报告；若宿主有文件交付工具，可将实际文件注册为交付物，否则给出本地绝对路径。不要使用Codex专有的消息指令作为DSH通用交付方式。

## 官方依据

- 本地发现及目录格式：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.zh.md
- 文件系统提供方：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md
- Skill加载与用户调用：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/tool-skill/README.md
- 浏览器提供方与会话归属：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/browser-use.zh.md
- Playwright MCP加载时机、工具名和窗口配置：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/experimental/browser-use-playwright-mcp/README.zh.md
- launch隔离模式实现：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/experimental/browser-use-playwright-mcp/src/index.ts

本适配以2026-10-14及2026-10-15所查官方说明为依据，并用本机DSH 0.2.0-rc.2的实际技能加载模块验证目录发现和加载。浏览器工具始终现场核实。
