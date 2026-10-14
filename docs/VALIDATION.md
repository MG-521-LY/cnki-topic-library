# 验证记录

日期：2026-10-14（Asia/Shanghai）。

## 本地任务工具

运行 `python skills/cnki-topic-library/tests/test_library_jobs.py`：

```text
Ran 21 tests in 14.950s
OK
```

覆盖1—99所有篇数、目标调整、100篇停止条件、失败补位、摘要证据约束、同名文章去重、缺失热度、重复/损坏文件、验证码暂停、并发写锁及报告导出。SHA-256计算采用分块读取，兼容Python 3.10，运行不依赖第三方包。

## 安装器

运行 `python -m unittest discover -s tests -v`：

```text
Ran 8 tests in 0.962s
OK (skipped=1)
```

7项通过：完整目录安装、安装后实际执行任务工具、拒绝未经指定的覆盖、备份更新、只读预览、项目目录安装、环境变量目录和源/目标重叠检查。1项“符号链接目标拒绝”因本机Windows没有创建符号链接权限而跳过；自动检查中能创建符号链接时执行，受限时也会明确标记跳过。

## DSH实际加载模块

使用本机DeepSeek Harness 0.2.0-rc.2所带的真实 `@deepseek-ai/dsh-skill-filesystem` 模块及Cordis Context，在隔离的自定义技能根目录中发现和加载本Skill，没有改动用户DSH配置。

验证结果见 [dsh-validation.json](dsh-validation.json)：

- 名称：`cnki-topic-library`。
- 模型可调用、用户可调用均为true。
- 完整Skill正文加载成功。
- 从提供方返回的资源基目录实际读取任务脚本及2份参考资料，3项均非空。

## 文献下载实测与边界

此前在Codex本机校园网浏览器中完成5篇真实下载，来自30条题录和8篇摘要评审；下载文件哈希唯一，能打开并渲染首页，达到5篇后队列停止。按实测补充隐藏验证码与新标签判断，以及下载事件超时后的文件核验流程。

尚未在DSH中执行真实知网全文下载，尚未完成真实100篇批量任务。DSH的浏览器后端、认证会话和文件保存能力仍需现场核实，不能把Skill加载成功等同于真实下载成功。

本仓库不包含下载的论文、机构凭据或个人浏览器配置。支持范围为Windows，GitHub CI使用Windows及Python 3.10/3.12；实际CI状态以Actions页面为准。
