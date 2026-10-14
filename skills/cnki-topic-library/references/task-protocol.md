# 本地任务协议

所有路径先替换成实际绝对路径；`<skill>`指本Skill的安装目录。通过文件工具生成UTF-8 JSON，不把用户文本拼成可执行shell代码。写命令时按当前shell正确引用路径。

```text
python <skill>/scripts/library_jobs.py init --task <任务目录> --topic <完整研究需求> --count <目标篇数>
python <skill>/scripts/library_jobs.py set-target --task <任务目录> --count <新目标总篇数>
python <skill>/scripts/library_jobs.py ingest --task <任务目录> --input <题录JSON文件>
python <skill>/scripts/library_jobs.py review --task <任务目录> --input <评审JSON文件>
python <skill>/scripts/library_jobs.py rank --task <任务目录>
python <skill>/scripts/library_jobs.py next --task <任务目录> --limit 5
python <skill>/scripts/library_jobs.py record --task <任务目录> --id <id> --status in_progress
python <skill>/scripts/library_jobs.py record --task <任务目录> --id <id> --status downloaded --file <文件路径>
python <skill>/scripts/library_jobs.py record --task <任务目录> --id <id> --status failed --reason <具体原因>
python <skill>/scripts/library_jobs.py status --task <任务目录>
python <skill>/scripts/library_jobs.py export --task <任务目录>
```

`init` 默认100篇，可传 `--count`、`--min-relevance`、`--allow-caj`；同目录已有任务时拒绝覆盖。没有自动联网或下载副作用。`next`返回数量不会超过目标缺口，正在下载的条目占用目标名额。支持状态为 `pending, in_progress, downloaded, failed, no_access, no_pdf, waiting_user`。暂停、失败条目不自动重试；修复后使用 `record ... --status pending` 重置单条。

`--count`支持1—10000的整数，1—99任意数字均可；宿主Agent负责将自然语言中的“三十篇”等表达转成30。“30”在已有主题/任务语境下表示总目标30；“再下载30篇”表示在当前成功数上追加30。年份和“近5年”不参与篇数解析。

`set-target`更新已有任务的总目标，记录修改历史，不修改论文、主题或评审。每次改动前会复查文件。下调目标时，已成功文件全部保留；如果现有成功数不小于新目标，队列停止新增。正在进行的浏览器下载由Agent检查并停止新增任务，工具不会取消宿主浏览器请求。

每次导入及评审为一个事务；无效数据导致整批拒绝，不部分写入。不要同时运行两个写入命令，同目录已被占用时工具拒绝并发。

## 题录导入

输入为对象数组，或 `{"papers": [...], "search_log": [...]}`。`search_log` 可记录查询、排序、页数、日期、停止原因等普通JSON信息。示意数据仅说明格式，不是已找到的论文：

```json
{
  "papers": [{
    "title": "从实际页面读取的论文标题",
    "authors": "实际作者",
    "year": 2024,
    "source": "实际期刊",
    "doc_type": "期刊",
    "field": "教育学",
    "url": "https://kns.cnki.net/实际详情路径",
    "cnki_id": "CJFD:实际filename",
    "doi": "",
    "abstract": "从实际页面读取的摘要",
    "keywords": ["实际关键词"],
    "citations": 42,
    "downloads": "1.2万",
    "query": "实际检索式"
  }],
  "search_log": [{"query": "实际检索式", "sort": "相关度", "page": 1}]
}
```

`id`由工具生成；导入返回ID和标题供后续评审。再次导入同篇时合并数据，新增查询记录。DOI优先，其次CNKI标识，然后兼容的标题+作者+年份。信息不足、有同名歧义时宁可保留多个候选，不仅因标题相同就合并。

## 评审导入

```json
[
  {
    "id": "导入返回的ID",
    "decision": "include",
    "relevance": 92,
    "evidence": "abstract",
    "reason": "根据实际摘要，说明其研究对象和机制为何满足用户要求。"
  }
]
```

`decision`为 `include` 或 `exclude`；`evidence`为 `title, abstract, fulltext`。声明摘要依据必须确实有摘要字段；全文依据需存在可核验的本地文件，或 `fulltext_note` 记录已实际阅读的正文段落位置及内容证据。`exclude`也保留理由。已下载后改成排除/低于门槛的文献从目标成功数移出，但不删除本地文件。改变影响筛选的元数据会撤销旧评审，保留文件与下载状态，待重新评审后再计数。

## 排名

综合分 = 0.8 × 相关性分 + 20 × 热度（0—1）。默认相关性门槛65，只有明确include且达到门槛者进入待下载队列。

候选同组：`field + doc_type + year_band`。年份段为2025—2029、2020—2024等5年段，未知年份单独成组。每个指标有效样本不足5个时使用0.5；否则用平均并列名次分位数 `(小于该值数量 + (等于该值数量-1)/2) / (样本数-1)`。被引、下载各自缺失时用0.5；均缺失的热度就是中性0.5。热度依据和缺失标志都写入记录。

排名只反映本次检索样本。不能推导知网全库排名，也不把热门度等同论文质量。`rank`只更新排名，不重置失败、不改动下载文件。

## 文件与报告

核验只接受本地已存在的普通文件：PDF需有 `%PDF-`文件头、结尾 `%%EOF` 且大小至少512字节；CAJ需显式启用且有支持的 `CAJ/CDS/KDH/TEB/HN`文件签名。不支持的原生格式据实拒绝。重复SHA-256不能按两篇计数。该验证是文件类型/截断初筛，不保证PDF完整结构有效。

`status`会复查文件路径、签名、SHA-256；发生删除/更改时降级为失败并记录原因。`export`生成 `library.csv`（UTF-8 BOM，便于表格软件打开）、`report.md`、`manifest.json`。CSV对公式前缀进行转义；CSV/报告不包含cookie或密码。任务JSON和报告只含书目信息、评审、查询和本地路径。

`export`的统计以符合当前筛选且文件有效的文献为准；报告显示未评审、排除、失败、等待处理和中断条目，不把未完成任务包装成已完成。
