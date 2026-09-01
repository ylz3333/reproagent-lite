# ReproAgent-Lite 逐文件 Code Review 指南

这份文档是项目的“审阅地图”。它回答四个问题：系统如何流转、每个目录负责什么、每个文件为什么存在，以及修改时必须守住哪些边界。

## 1. 一句话理解项目

ReproAgent-Lite 把一条论文结果写成执行前冻结的任务契约，在受限环境中按多个随机种子运行官方实验代码，从机器可读指标中计算确定性 verdict，并保存可复核的来源、日志、指标和哈希。

```text
论文 PDF / 人工提示
        │
        ▼
候选数值 + 页码证据 ──人工确认──► task.json（实验前冻结）
                                        │
                                        ▼
                                 严格解析与路径校验
                                        │
                            ┌───────────┴───────────┐
                            ▼                       ▼
                     来源/commit/哈希          Docker 隔离执行
                                                    │ 每个 seed 独立
                                                    ▼
                                               metrics.json
                                                    │
                                                    ▼
                              确定性聚合与容差判断（不调用 AI）
                                                    │
                                                    ▼
                                  verdict.json + report.md + 证据哈希
```

最重要的职责分离：`paper.py` 和可选的 `llm.py` 只帮助找到“论文可能说了什么”；`verifier.py` 才判断实验是否满足预注册容差，而且该判断完全确定、可测试、不依赖模型。

## 2. 建议的 Review 顺序

第一次阅读不要从第三方 GCN 算法细节开始。按下面顺序，大约 30–45 分钟可以掌握主干：

1. `README.md`：产品目标、快速运行方式和限制。
2. `examples/linear-regression/task.json`：最小任务契约长什么样。
3. `src/reproagent_lite/models.py`：任务进入系统时如何 fail closed。
4. `src/reproagent_lite/workflow.py`：主业务流程和证据生命周期。
5. `src/reproagent_lite/runner.py`：本地/Docker 执行边界。
6. `src/reproagent_lite/verifier.py`：PASS、FAIL、INCONCLUSIVE 的唯一判定点。
7. `src/reproagent_lite/hashing.py` 与 `report.py`：证据完整性和展示。
8. `src/reproagent_lite/paper.py` 与 `llm.py`：论文候选提取，注意它们不参与 verdict。
9. `tests/`：用测试反向核对上述契约。
10. `case-studies/gcn-cora/`：把通用框架映射到真实论文。

## 3. 顶层目录

| 路径 | 类型 | 作用 | Review 提示 |
|---|---|---|---|
| `src/` | 一方源码 | 可安装的 ReproAgent-Lite Python 包 | 业务逻辑的主要审阅对象 |
| `tests/` | 一方测试 | 安全、模型、执行、验证和端到端契约 | 修改主流程时必须同步扩展 |
| `examples/` | 一方示例 | 无下载、低风险、快速验证框架本身 | 适合学习任务格式和本地调试 |
| `case-studies/` | 案例 + 第三方源码 | 真实 GCN/Cora 论文复现 | 区分我们的包装层与冻结上游代码 |
| `docs/` | 一方文档 | 架构、任务格式和逐文件审阅指南 | 行为或接口变化时同步修改 |
| `runs/` | 运行生成物 | 每次实验的完整证据包 | 可删除重跑，不应作为源码编辑 |
| `demo-output/` | 示例生成物 | 已生成的演示证据 | 用于浏览输出结构，不是判定逻辑 |
| `build/` | 构建生成物 | 打包工具复制出的 Python 模块 | 不直接改；改 `src/` 后重新构建 |
| `*.egg-info/` | 安装生成物 | 包元数据和文件清单 | 不直接改；由安装/构建命令刷新 |
| `__pycache__/` | 解释器缓存 | Python 字节码 | 不审阅、不提交，删除后会自动再生 |
| `.vs/` | IDE 缓存 | Visual Studio 本地状态 | 与项目功能无关，不审阅、不提交 |

## 4. 顶层文件

| 文件 | 做什么 | 关键点 |
|---|---|---|
| `.gitignore` | 排除缓存、虚拟环境、构建物、运行证据和本地密钥文件 | 新增生成目录时应同步维护 |
| `.gitattributes` | 统一跨平台文本换行，并把 PDF/数据文件标为 binary | 避免另一台电脑出现整文件伪 diff |
| `pyproject.toml` | 定义包名、Python 版本、可选 PDF/OpenAI 依赖、CLI 入口和构建方式 | 依赖应尽量可选；核心 verifier 保持轻量 |
| `README.md` | 面向使用者的入口文档 | 命令、输出和安全承诺必须与代码一致 |
| `SECURITY.md` | 威胁模型、信任边界和负责任使用说明 | Docker 是隔离层，不是恶意代码的绝对安全证明 |
| `LICENSE` | 项目 MIT 许可 | 不包含上游 GCN 的单独许可；上游许可保留在其目录 |
| `run-gcn-smoke.cmd` | Windows 双击启动三 seed 冒烟复现 | 仅做入口转发，不保存科学参数 |
| `run-gcn-full.cmd` | Windows 双击启动 100 seed 正式复现 | 耗时明显更长；使用与 smoke 相同的代码路径 |

## 5. `src/reproagent_lite/`：一方核心代码

### `__init__.py`

包的公共入口和版本导出。这里应保持小而稳定，避免导入时触发 Docker、网络或文件系统操作。

### `__main__.py`

让 `python -m reproagent_lite ...` 与安装后的 `reproagent ...` 使用同一个 `cli.main()`。它只负责把退出码交还给 shell。

### `cli.py`

命令行适配层，注册五类命令：

- `validate`：严格解析并打印规范化任务；
- `run`：执行指定任务；
- `demo`：运行可信的线性回归夹具；
- `extract`：从 PDF 生成待确认 claim 草稿；
- `doctor`：检查 Python、Docker 和可选依赖。

它不实现科学逻辑。退出码是外部契约：`0` 为成功/PASS，`1` 为配置或运行错误，`2` 为已完成但没有 PASS。

### `models.py`

系统的严格 JSON 边界。所有核心对象都是不可变 dataclass：

- `EvidenceSpec`：论文字段对应的原文、页码、表格和置信度；
- `PaperSpec`：PDF 和上游仓库 origin/commit；
- `SourceSpec`：源码目录、argv 命令、结果文件和指标键；
- `AcceptanceSpec`：聚合方式、最少成功 seeds、绝对/相对容差；
- `ClaimSpec`：论文报告指标和值；
- `ExecutionSpec`：seeds、超时、CPU、内存和网络策略；
- `TaskSpec`：完整任务契约；
- `AttemptRecord`：单个 seed 的标准化结果；
- `VerificationResult`：最终确定性判定。

Review 重点是 fail-closed：未知字段、重复键、NaN/Infinity、真假值冒充数字、重复 seed 和无法满足的最少 seed 数都会被拒绝。

### `security.py`

可复用的输入/执行边界：

- `resolve_inside()` 防止 `../` 或绝对路径逃出注册根目录；
- `validate_command()` 只接受 argv 列表并拒绝控制字符，执行时永不启用 shell；
- `minimal_environment()` 构造最小子进程环境，不复制 API key、云凭据和代理变量。

这里是高风险修改区。增加环境变量白名单或放宽路径/命令规则时，需要相应的负向测试。

### `hashing.py`

计算文件和源码树的 SHA-256。树哈希同时绑定相对路径与文件内容，因此移动整个项目不会改变哈希，但重命名/修改输入会改变哈希。`.git` 和 `__pycache__` 不属于实验输入，被明确排除。

### `runner.py`

执行后端及统一结果对象：

- `RunLimits`：资源/网络上限；
- `ExecutionResult`：进程结果及 stdout/stderr/output 路径；
- `ExperimentRunner`：后端接口；
- `LocalRunner`：只用于显式确认的可信夹具，没有隔离；
- `DockerRunner`：构建内容寻址镜像并为每个 seed 启动一次性容器；
- `write_execution_record()`：写可迁移的执行 JSON。

Docker 防线包括只读根文件系统和源码挂载、非 root 用户、丢弃 capabilities、`no-new-privileges`、无 IPC、PID/CPU/内存/文件句柄限制、受限 `/tmp`、独立可写输出目录、默认无网络，以及超时后的强制清理。

### `workflow.py`

应用服务层和主状态机：

```text
PREPARING → PREPARED → RUNNING → REPORTED
```

`prepare()` 在执行前写规范化任务、claim、plan、来源清单和哈希，并核对 Git origin/commit；`run()` 为每个 seed 创建独立 attempt，读取指标，调用 verifier，然后同时输出机器 verdict 和 Markdown 报告；`_attempt_record()` 把进程失败、超时、指标损坏和成功统一成结构化记录。

所有关键 JSON 使用临时文件后原子替换，避免 UI 或 reviewer 读到半写文件。Git 的 safe-directory 通过一次性临时配置处理，不修改用户全局 Git 配置。

### `verifier.py`

唯一的科学判定模块：

1. 从注册的 `result_file` 和点分 `metric_key` 读取有限数值；
2. 成功 seed 不足时返回 `INCONCLUSIVE`；
3. 按预注册方法计算 mean/median/min/max；
4. 按预注册绝对/相对容差返回 `PASS` 或 `FAIL`；
5. 附上证据哈希。

这里不得加入 LLM 判断、事后调整容差或从 stdout 猜测指标。

### `report.py`

把结构化结果渲染为给人看的 `report.md`。它是 view，不是 source of truth；自动化应读取 `verdict.json`。本地后端会明确显示未隔离警告。

### `paper.py`

确定性论文候选提取：通过 PyMuPDF 按页抽取文字，寻找与 target hint 局部共现的数字，使用透明启发式排序，并保留原文、页码和附近表号。百分数保持论文显示尺度，例如 `81.5%` 仍记录为 `81.5`，不会偷偷变成 `0.815`。

输出只是 `ClaimDraft`，必须由人确认后才能进入 task。

### `llm.py`

可选 OpenAI 辅助层。SDK 在真正调用时才动态导入，因此核心项目不需要 API key。模型输入带精确页码并限制长度，论文文本被标记为不可信材料；响应必须是 JSON 对象。

模型只能丰富 claim 草稿，不能执行代码、选择最终容差或产生 verdict。

## 6. `examples/linear-regression/`

| 文件 | 作用 |
|---|---|
| `task.json` | 最小完整任务：3 个 seeds、RMSE 指标、预注册均值和绝对容差 |
| `experiment.py` | 标准库生成固定数据，用 seed 决定 train/test split，拟合 OLS 并写 `metrics.json` |
| `Dockerfile` | 无第三方依赖的最小镜像；也可用显式 opt-in 的 local backend |

这个目录验证“框架是否正常”，不复现某篇真实论文。严格 JSON 不支持注释，字段解释统一放在 `docs/TASK_FORMAT.md`，避免为了注释把任务文件变成非标准格式。

## 7. `tests/`

| 文件 | 覆盖的契约 |
|---|---|
| `test_models.py` | 任务 round-trip、未知字段、重复键、非有限数、seed/容差约束 |
| `test_security.py` | 路径逃逸、控制字符和凭据不进入子进程 |
| `test_hashing.py` | 树哈希忽略 Git 元数据和 Python 缓存 |
| `test_runner.py` | local 显式授权、seed/output 注入、Docker 参数、构建失败和超时清理 |
| `test_verifier.py` | 指标读取以及 PASS/FAIL/INCONCLUSIVE |
| `test_paper.py` | 页码证据、候选排序、PDF 可选依赖、注入式 LLM 客户端和坏响应 |
| `test_workflow.py` | demo 端到端证据包、可迁移路径、Git provenance 和脏工作树记录 |

测试名本身描述行为，模块和测试类 docstring 解释所属边界。新增重要行为时，优先写“错误输入必须失败”的测试，而不只覆盖 happy path。

## 8. `case-studies/gcn-cora/`：真实论文案例

### 我们维护的案例包装层

| 文件 | 作用 | 是否可直接修改 |
|---|---|---|
| `README.md` | 论文结果、smoke/full 差异、运行和解释协议 | 可以，行为变化时同步更新 |
| `paper/gcn-paper.pdf` | ICLR 2017 论文原文证据 | 不应编辑；替换需重新核对哈希和任务 |
| `task-smoke.json` | 3 seeds 工程冒烟；快速确认整条管线 | 可以，但改动必须视为新预注册任务 |
| `task-full.json` | 100 seeds、与论文报告习惯更接近 | 同上 |
| `run-task.ps1` | Windows 环境发现、Docker 健康检查、CLI 退出码处理 | 可以；不要把容差/结果写进脚本 |

当前 smoke 任务使用 seeds `7, 19, 42`，报告值 `81.5`，以均值和预注册绝对容差判定。它证明工程链路可运行，不等价于复现论文全部实验。

### `experiment/upstream/`：冻结上游 + 最小 instrumentation

该目录本身是官方仓库的 Git checkout，注册 commit 为 `39a4089fe72ad9f055ed6fdb9746abdcfebc4d81`。为了维持来源可审计性，不给上游算法文件批量加我们的注释；我们的改动必须能由 `patches/0001-reproagent-instrumentation.patch` 单独解释。

| 文件 | 作用 | 所有权/策略 |
|---|---|---|
| `.git/` | 上游 origin、commit 和 worktree 状态 | provenance 元数据，不手工编辑 |
| `.gitignore` | 官方仓库原有的忽略规则 | 上游冻结文件 |
| `.dockerignore` | 排除 `.git` 和 Python 缓存，缩小/稳定镜像构建上下文 | 一方 overlay，可审阅修改 |
| `README.md` | 官方运行与模型说明 | 上游冻结文件 |
| `LICENCE` | 上游代码许可 | 必须保留 |
| `setup.py` | 官方 Python 包配置 | 上游冻结文件 |
| `requirements.txt` | 官方历史依赖声明 | 参考信息；可运行版本由 Dockerfile 精确固定 |
| `Dockerfile` | 我们重建 Python 3.7/TensorFlow 1.15 兼容环境 | 一方 overlay，可审阅修改 |
| `PROVENANCE.json` | 记录官方 URL、commit、论文、数据和 instrumentation 来源 | 一方 overlay；来源变化必须更新 |
| `patches/0001-reproagent-instrumentation.patch` | 对官方 `gcn/train.py` 的最小可复核改动 | 一方 overlay；应可反向/重新应用 |
| `run_gcn.py` | 从上游期望的 cwd 启动训练并保留 import/data 路径语义 | 一方 overlay |

### 上游 `gcn/` Python 文件

| 文件 | 上游职责 |
|---|---|
| `gcn/__init__.py` | 声明 Python 包 |
| `gcn/inits.py` | TensorFlow 权重初始化器 |
| `gcn/layers.py` | 图卷积、稠密层和 dropout 等层实现 |
| `gcn/metrics.py` | masked loss 与 masked accuracy |
| `gcn/models.py` | GCN/MLP 模型组装、优化和训练操作 |
| `gcn/utils.py` | 数据加载、稀疏矩阵预处理、邻接归一化和 feed dict |
| `gcn/train.py` | 官方训练入口；最小 patch 读取 seed、设随机源并写机器可读 `metrics.json` |

Review `train.py` 时先看 patch，而不是把整份历史 TensorFlow 代码当成我们新写的代码。核心问题是 instrumentation 是否只增加可重复性和输出，不改变模型结构、数据切分或论文指标定义。

### 上游 `gcn/data/` 数据文件

三个数据集前缀为 `ind.cora`、`ind.citeseer`、`ind.pubmed`。每个数据集包含相同角色的文件：

| 后缀 | 含义 |
|---|---|
| `.x` / `.y` | 有标签训练节点的特征 / 标签 |
| `.tx` / `.ty` | 测试节点的特征 / 标签 |
| `.allx` / `.ally` | 训练节点加无标签节点的特征 / 标签 |
| `.graph` | 节点邻接表 |
| `.test.index` | 测试节点 ID 及其恢复顺序 |

Cora 案例实际使用 `ind.cora.*`。Citeseer 和 Pubmed 文件是官方仓库一部分，保留它们可维持 checkout 完整性，但本任务不会读取。二进制数据不添加行内注释；其角色由本节和上游 README 解释。

## 9. `docs/`

| 文件 | 面向对象 | 内容 |
|---|---|---|
| `ARCHITECTURE.md` | 设计/安全 reviewer | 组件关系、信任边界和威胁模型 |
| `TASK_FORMAT.md` | 新任务作者 | 每个 JSON 字段、约束和例子 |
| `CODE_REVIEW_GUIDE.md` | 新开发者/reviewer | 本文：逐目录、逐文件、阅读顺序和修改规则 |

文档职责不同但不能互相矛盾。新增任务字段时至少更新 `models.py`、`TASK_FORMAT.md` 和模型测试；改变安全承诺时同步更新 `SECURITY.md` 与 `ARCHITECTURE.md`。

## 10. 每次运行产生的文件

`runs/<task-name>/` 是 append/overwrite 式证据工作区，不是源码：

| 文件 | 由谁产生 | 怎么看 |
|---|---|---|
| `state.json` | workflow | 最新状态快照，适合快速看进度 |
| `task.normalized.json` | models + workflow | 实际执行的规范化任务 |
| `claim.json` | workflow | 冻结的 metric、reported value 和容差 |
| `plan.json` | workflow | 执行前记录的 seeds、backend 和阶段 |
| `source_manifest.json` | workflow + hashing | PDF、任务、源码树、origin、commit 和脏改动 |
| `attempts/seed-N/stdout.log` | runner | 上游程序标准输出 |
| `attempts/seed-N/stderr.log` | runner | 上游程序警告/错误 |
| `attempts/seed-N/execution.json` | runner | argv、backend、耗时和退出状态 |
| `attempts/seed-N/metrics.json` | 实验代码 | verifier 唯一读取的机器指标 |
| `attempts.json` | workflow | 所有 seed 的统一索引 |
| `verdict.json` | verifier + workflow | 自动化使用的 source of truth |
| `report.md` | report | 给人阅读的结果视图 |

证据哈希能发现文件在运行后是否变化，但当前 MVP 没有签名/远程时间戳，因此不能证明由谁产生。需要更强合规性时，应把证据包上传到不可变对象存储并签名。

## 11. 任务 JSON 字段如何进入系统

严格 JSON 不允许注释，下面是字段到代码的映射：

| JSON 区域 | 读取模型 | 下游消费者 |
|---|---|---|
| `paper` | `PaperSpec` | workflow 校验 PDF、origin、commit 并计算哈希 |
| `source` | `SourceSpec` | runner 执行 argv；verifier 读取 result file/key |
| `claim` | `ClaimSpec` | verifier 获取 metric、reported value 和 acceptance |
| `execution` | `ExecutionSpec` | workflow 遍历 seeds；runner 应用资源/网络限制 |

`source.command` 是字符串数组，不是 shell 字符串。`{python}` 是唯一的便携占位符：local backend 替换为当前解释器，Docker backend 替换为容器中的 `python`。

## 12. 修改规则与常见扩展点

- 新增聚合方式：修改 `AcceptanceSpec.AGGREGATIONS` 和 `verifier._aggregate()`，补模型与 verifier 测试，并更新任务格式。
- 新增执行后端：实现 `ExperimentRunner`，产出同样的 `ExecutionResult`，然后在 workflow/CLI 显式注册；不能绕过证据记录。
- 新增论文格式：扩展 `paper.py` 的读取层，保持页码 evidence；不要让解析器直接写可执行 task。
- 支持新的 ML 框架：优先写小型 instrumentation adapter 产生 `metrics.json`，不要让 verifier 解析非结构化 stdout。
- 修改容器权限：先写负向 runner 测试，再更新 `SECURITY.md`；网络仍应默认关闭。
- 修复第三方论文代码：生成最小 patch、记录原因和上游 commit，不直接把来源历史改得无法比较。

## 13. Review 完成标准

一次修改可以合并前至少确认：

1. 行为是否仍由执行前任务决定，而不是看到结果后调整；
2. 每个成功 seed 是否有 execution、stdout、stderr 和 metrics 证据；
3. 失败/缺失是否得到 INCONCLUSIVE 或结构化错误，而不是被忽略；
4. 是否保持 `shell=False`、路径 containment、最小环境和默认无网络；
5. AI 是否仍停留在候选提取层，未进入 verdict；
6. 第三方改动是否最小、可追溯、能由 patch 解释；
7. 测试、编译、任务校验和相关文档是否同步通过。
