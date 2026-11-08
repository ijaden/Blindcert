# BlindCert：Ubuntu 端到端效率实验实施说明

## 1. 任务与范围

请在 Ubuntu 虚拟机中，基于现有 BlindCert 仓库修复真实端到端实现，再完成效率测量并导出两张论文表格。

- 仓库：<https://github.com/ijaden/Blindcert>
- 本说明核对的提交：`0e480001c8712e4d96bd5216ee76b038acf895a4`。
- MPC 固定为 **3 方 MP-SPDZ/MASCOT**；co-ZK 固定为 **3 方 co-circom/Groth16/REP3**。首轮由同一组 3 个逻辑参与者执行两阶段。
- 部署在同一台 Ubuntu 虚拟机，使用独立参与方进程和各自的输入、份额目录。记录虚拟机实际分配的 CPU、内存及宿主机信息。
- 固定模型所有者 1 个、数据持有者 2 个、分层数 2 个。角色可以与上述 3 方重合。
- 唯一正式变化维度是模型类型与规模。所有主实验使用同一组基准总量、抽样量、数值精度和系统配置。
- 不增加参与方数量扫描、LAN/WAN 扫描、故障/攻击实验、消融实验、额外数据集评估或 LLM 实验。
- 允许修改实现、补齐电路和份额转换、修复依赖兼容问题。用户已经授权将修改后的代码上传 GitHub；用独立分支提交并推送，保留原有历史。
- 仅需要做一次实验即可，不需要做五次实验取平均值。

本文件是交给 Ubuntu 端执行者的任务说明。文中的时间、约束数、证明大小均须由实际运行产生；`TBD` 表示尚未测量。

## 2. 两张表的最终形式

### Table 1：完整系统耗时，替换原组件耗时表

每个模型一行，主表只保留以下四列，使所有模型的系统总成本可直接比较：

| Model | Setup (s) | End-to-end (s) | First-use total (s) |
| --- | --- | --- | --- |
| 各模型名称 | 一次准备实测 | 一次实验 | 首次完整运行实测 |

`End-to-end` 覆盖一次真实认证从登记到公开验证完成的全部运行阶段。`Setup` 单列编译和密码学设置成本；`First-use total` 覆盖空制品目录下的准备工作与首次认证。三个字段的边界见第 5 节。

各阶段时间仍写入 JSON/CSV，供分析总成本使用，不另加第三张论文表格。Table 1 与 Table 2 使用相同的模型清单。

### Table 2：严格保留现有八列，扩充模型行

表头、顺序和单位保持为：

| Model | Constraints | Private inputs | Single prove (s) | Co-witness (s) | Co-prove (s) | verify (s) | Proof size (KB) |
| --- | --- | --- | --- | --- | --- | --- | --- |

“不同模型的验证时间”对应其中的 `verify (s)`；其余七列按原格式保留。原有模型也在新的三方端到端实现上重测，不直接沿用旧表数值。

## 3. 现有代码必须补齐的连接

已经核对的代码事实：

| 位置 | 当前实现 | 本次需要完成的工作 |
| --- | --- | --- |
| `blindcert/session.py`、`blindcert/cli.py` | 默认端到端入口使用 Mock MPC/Mock proof；部分配置参数未真正驱动执行 | 增加由配置驱动的真实三方入口，主实验明确选择真实后端 |
| `blindcert/mpc/mpspdz_backend.py` | 读取 P0 模型和 P1 数据；返回的 `witness_shares` 是执行结果描述字典 | 将三方数量实际传给启动器；两个持有者分别输入其记录；返回实际秘密份额 |
| `blindcert/protocol/prove.py` | 将第一份 `share.value` 当作完整明文 Witness 执行关系检查 | 为真实后端接入秘密份额路径，由 MPC 与证明电路执行相应检查 |
| `scripts/run_full_protocol.py` | MPC 与证明分别取输入；协作证明存在 `split-witness` 回退 | 建立同一次会话、同一批输入、同一份见证的连续交接 |
| `scripts/run_efficiency_benchmark.py` | 各组件分开测量，证明阶段使用从完整明文见证拆出的份额 | 改成一个外层计时器包围真实流程，复用实际 MPC 输出 |
| `scripts/run_larger_model_experiments.py` | 样本数固定为 4；部分模型/数值语义与 Python 后端不同 | 参数化模型、电路和公共工作负载，统一各后端计算语义 |
| `blindcert/protocol/verify.py`、`blindcert/proofs/collaborative_backend.py` | 公共验证入口未接通真实 collaborative 后端；证明公共输入尚需与预期 statement 对照 | 接通真实公开验证，显式检查公共输入向量与登记对象及会话的一致性 |
| `circuits/` | 当前提交缺少 LR-4 脚本引用的电路文件 | 提交可复现的电路源码、依赖和生成器 |

现有 `SingleProverBackend` 继承 Mock 后端。Table 2 的单证明者数据必须使用真实 `snarkjs Groth16` 或等价真实实现，不能使用该开发后端的耗时。

### 连续数据流

一次系统测量依次完成：

1. 各方读取自己的私有输入，生成模型承诺和完整基准的认证根，登记策略和唯一会话。
2. 三方执行 Commit–Reveal，产生本次候选样本和公共 transcript。
3. 输入共享；三方 MASCOT 执行已登记模型的评估及认证关系所需计算。
4. 导出真实见证份额，完成 MAC 验证、重分享和 co-circom 格式适配。
5. 从这些份额完成协作见证扩展/准备，生成证明系统要求的完整 R1CS 见证。
6. 三方生成 Groth16 证明，封装 Passport 和公共 transcript。
7. 独立验证进程只读公共认证包与验证材料，检查会话、样本、公共输入及真实证明，返回接受结果。

其中第 4 步是协议实现工作，不是把两种份额文件改名。需要统一 BN254 **标量域**、符号与定点编码、参与方份额布局、见证线序和常数线/公共输入位置。根据锁定版本的实际接口实现转换，核对 MAC 检查与重分享的顺序以及实际腐化阈值。

第 5 步统一记作 `Co-witness`：转换后的秘密份额被扩展、组装并写成协作证明需要的见证。该阶段与 MPC、份额转换分开计时；所有模型采用同一条实现路径。若辅助线已在 MPC 内生成，准备阶段应实际记录其余组装工作，不能重复计入 MPC 时间。

系统流程中的见证始终以秘密份额交接。完整明文见证仅可用于独立的单证明者对照，放在单独目录，不作为系统证明的输入。真实后端缺失、份额交接失败或验证未接受时，记录失败和日志，不回退为 Mock 或 `split-witness` 后继续报告成功。

固定三方是部署设置；实现所支持的安全性质按实际后端和配置记录。正常路径的功能自检属于实现验收，不新增故障或攻击实验。

## 4. 模型与公共工作负载

### 模型清单

：

| 顺序 | 论文行名 | 结构说明 |
| --- | --- | --- |
|      |                      |                                                              |
|      |                      |                                                              |
| 3 | LR-D64 | 64 维线性分类器 |
| 4 | MLP-D16-H8 | 16 输入、8 隐藏单元、1 输出 |
|      |                      |                                                              |
| 6 | polynomial SVM-D16,2 | 16 维输入，二次显式特征映射的线性分类器，包含常数、线性项和全部二次交互项 |
| 7 | LR-D256 | 新增，256 维线性分类器 |
|      |                      |                                                              |
| 9 | MLP-D128-H64 | 新增，128 输入、64 隐藏单元、1 输出 |
|      |                      |                                                              |

你再帮我找一下更大的模型，不要都是小规模的实验模型。考虑实用价值。

MLP 沿用论文原实验的二次激活。将 Python、MP-SPDZ 和 Circom 的激活、阈值和算术范围统一，不能把 ReLU 版本和二次激活版本混作同一模型。带偏置的最后两个 MLP 分别约有 8,321 和 41,217 个参数，最终数量由实际模型导出器计算。

SVM 的固定判别函数为 `b + sum_i(w_i*x_i) + sum_{i<=j}(a_ij*x_i*x_j)`，按固定阈值输出二分类结果；在三个后端中使用同一系数顺序和算术关系。

“更大规模”用实际参数数目、R1CS 约束数和私有输入数说明；不预填预计约束数，也不将这些模型称作 LLM。

### 固定配置

- 建议主实验统一使用总基准 `N=1024`、总抽样量 `m=128`，两个 strata，各取 64 条；两个持有者按相同规则持有固定分区。
- 使用固定生成种子的有界合成模型与输入，作为效率工作负载。模型维度随行变化，其余工作负载规则一致。参数、标签及合法成功用例在登记和抽样之前准备并固定；这组实验不测泛化准确率。
- 沿用整数/定点关系；在 manifest 中固定量化精度、舍入、符号解释、累加器位宽和每层范围。大模型应重新推导范围，不能沿用小模型的 32 位比较而产生溢出。
- 策略包含实际执行的精度与安全计数、统计裕量及合法统计预算；在抽样前检查其可行性。使用总体权重计算聚合指标，Python/MPC/电路保持一致。
- 基准根认证完整的 `N` 条记录；证明验证被抽样记录的成员路径。不能只对被选记录重新生成一个根并称为登记基准。
- 每次测量使用新的会话标识和诚实随机贡献。固定的是工作负载生成种子，不是所有会话共用同一个硬编码挑战。

预检查先读取虚拟机 CPU、内存、可用磁盘及所需指令集，并验证目标配置能否容纳。`N=1024,m=128` 是建议配置，不是已经确认的可运行结果。如果整体资源不足，可在正式测量前统一降低全体模型的固定抽样量并重新确定统计裕量，记录一次配置变更，然后从头测量全部模型。不能只对某个大模型减少样本而继续放进同一可比表。

对于确定配置下仍然超时或内存不足的模型，保留该行并标记 `OOM` / `TIMEOUT` / `NOT_IMPLEMENTED`，同时保存真实原因；不能用估算值补齐。

## 5. 计时边界

### 会话端到端时间 `T_e2e`

使用同一协调进程的单调时钟，例如 `time.perf_counter_ns()`：

- **开始**：启动本次会话的参与方工作进程、读取本次私有输入和验证材料之前。
- **结束**：公共认证包完成写入、独立验证器返回结果且本次参与方工作进程已正常结束之后。

该闭合区间包含进程启动、输入读取、承诺/建树/登记、Commit–Reveal、输入共享、MPC、份额持久化与转换、协作见证准备、协作证明、封装、文件 I/O、通信等待及公开验证。

数据/模型生成和软件安装在实验准备阶段完成；电路编译和密码学设置计入下面的 Setup。单证明者对照不属于 BlindCert 认证路径，在系统计时区间之外运行。

阶段明细至少记录：

| 字段 | 内容 |
| --- | --- |
| `startup_input_s` | 启动与读取本次输入 |
| `registration_s` | 承诺、建树、登记 |
| `challenge_s` | Commit–Reveal 与样本产生 |
| `input_sharing_s` | 私有输入共享 |
| `mpc_s` | 三方私有计算，包括该会话实际消耗的预处理 |
| `conversion_s` | MAC 检查、重分享、格式适配 |
| `co_witness_s` | 协作见证扩展/准备 |
| `co_prove_s` | 三方协作证明 |
| `packaging_s` | Passport 与 transcript 序列化 |
| `verify_s` | 独立公共验证，含 transcript、公共输入和证明检查 |
| `finalize_s` | 其余正常收尾 |
| `e2e_s` | 外层完整会话墙钟时间 |

阶段使用不重叠的父区间；并行三方的阶段耗时取“第一方启动前到最后一方结束后”的墙钟区间，不把三方用时相加。`e2e_s` 必须直接测量，不能由独立组件实验拼接；若分项与总时间有差值，记录未覆盖开销或计时重叠，不能强行改数。

MASCOT 若使用在线生成的预处理，包含在本次会话中；若提前生成，单列实际消耗的预处理成本，计入首次准备/运行总成本，并说明计费边界。不得把 triples 生成成本同时从 Setup 和会话总时间中省略。

### 准备时间与首次总时间

对每个模型从空的模型制品目录开始，记录一次：

- `setup_s`：电路生成与编译、该模型所需 SRS 的准备/校验、Groth16 设置、PK/VK 导出及固定配置初始化。通用软件安装不计入。使用外部已有 SRS 时，记录来源，并明确 Setup 只包含获取/校验与电路专属设置，不将其冒称为 SRS 生成成本。
- `first_use_total_s`：由同一个外层时钟直接测量，从上述首次准备开始，到首次真实会话公开验证和正常收尾完成。包括两者之间的实际协调开销。

该模型其余会话复用编译制品和证明密钥。Setup 与首次总时间各测一次；会话时间报告 5 次独立会话的均值与样本标准差。首次会话可作为这 5 次中的第一次，注明操作系统文件缓存未强制清空。

`First-use total` 是首次完整运行的实际值，不是 Setup 加上不同运行的平均会话时间。两张表脚注明确上述口径。

## 6. Table 2 各列的精确定义

- **Constraints / Private inputs**：从该模型实际生成的 R1CS 提取，属于完整认证关系，含承诺/成员验证/推理/策略约束。
- **Single prove (s)**：真实单证明者 Groth16 证明时间，包含该证明命令正常读取密钥与见证的成本，排除见证生成、Setup 与验证；与系统使用相同电路、密钥、模型和样本。
- **Co-witness (s)**：第 3 节定义的协作见证准备区间，不重复计算 MPC 与转换时间。
- **Co-prove (s)**：由本次实际见证份额完成三方协作证明的阶段墙钟时间。
- **verify (s)**：与端到端流程相同的独立公共验证区间，不以另一个纯密码学验证微基准替代。可额外将 SNARK 内核验证时间保存在原始结果中，供解释开销。
- **Proof size (KB)**：实际 Groth16 proof 对象采用统一紧凑 JSON 编码后的 UTF-8 字节数除以 1024，不包含 public inputs、VK、transcript 或整个 Passport。另存整个认证包字节数，不能把 0.71 KB 写成预期常量。

时间列报告 5 次运行的算术均值，原始结果另外保存标准差、中位数、最小值和最大值。表中验证器、计时方法和单位统一，旧表的 0.247 s / 0.007 s 数字全部以新测量替换。

## 7. Ubuntu 执行顺序与入口要求

### A. 获取代码与记录环境

下面是可直接执行的仓库准备命令；如果已经有本地仓库，先保留已有修改，再进入该仓库使用工作分支。

当前项目要求 Python 3.11 或更新版本。先确认 `python3` 满足要求；否则使用已安装的兼容解释器替换下面的 `python3`。实现读取 YAML 的配置入口时，将实际需要的 YAML 解析依赖写入项目依赖清单。

```bash
git clone https://github.com/ijaden/Blindcert.git
cd Blindcert
git switch -c experiment/system-e2e-three-party
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
git rev-parse HEAD
uname -a
lscpu
free -h
df -h .
```

锁定 MP-SPDZ、co-circom、Circom、snarkjs、Node 和 Python 的实际版本/提交，补齐依赖和可构建说明。现有安装脚本目标为 MP-SPDZ 0.4.3、co-circom 0.9.0；如果需修复旧版份额兼容问题而更新版本，记录原因及新提交，用新版本重测全部模型。三个 MPC 进程必须实际启动，不能只修改 `party_count` 字段。

### B. 完成实现与正常路径自检

先打通一个小模型的真实完整会话，再复用同一数据流到全部模型。对照独立整数参考实现，确认正常输入下模型预测、计数、公共输入和验证结果一致；该自检不作为额外论文实验。

### C. 实现统一实验接口后测量

以下是**要求实现的接口**，当前旧版脚本尚不支持全部参数。先修改脚本并通过 `--help` 核对，再执行，不能直接把旧命令输出当作新实验结果。

优先重构现有 `scripts/run_efficiency_benchmark.py`，由 `configs/system_efficiency.yaml` 驱动；让旧 larger-model 脚本复用同一实现。配置至少包含：

```yaml
mpc_backend: mpspdz
mpc_protocol: mascot
mpc_parties: 3
proof_backend: collaborative
proof_system: groth16
proof_protocol: REP3
proof_parties: 3
holders: 2
strata: 2
population_size: 1024
sample_size: 128
iterations: 5
workload_seed: 20261105
output_dir: results/system_efficiency
# 模型列表、数值精度、固定策略/裕量和资源上限按本说明补齐。
```

目标命令：

```bash
# 检查环境、模型清单与配置，不生成性能结论。
python scripts/run_efficiency_benchmark.py \
  --config configs/system_efficiency.yaml --preflight

# 空的模型制品目录下测量 Setup、首次总时间和五次真实会话；
# 在端到端区间之外补测 Single prove。
python scripts/run_efficiency_benchmark.py \
  --config configs/system_efficiency.yaml \
  --iterations 5 --output results/system_efficiency

# 只从实际保存的结果导出两张表。
python scripts/export_latex_table.py \
  --input results/system_efficiency/summary.json \
  --output results/system_efficiency/tables
```

每个模型、会话、单证明者对照各使用独立目录。测量按顺序运行模型，固定线程配置；记录进程/容器资源限制。对大模型设置明确超时和内存预算，保留未完成状态与日志，避免无限重启。

## 8. 结果文件与复现信息

```text
results/system_efficiency/
  environment.json
  effective_config.yaml
  model_manifest.json
  setup.jsonl
  runs.jsonl
  summary.json
  summary.csv
  tables/
    table1_end_to_end.tex
    table2_model_scaling.tex
  logs/<model>/<run_id>/...
```

`runs.jsonl` 每次会话记录：模型及结构、参数数目、源代码提交、会话标识、N/m、各方数量、后端、制品/公共输入摘要、所有阶段时间、`e2e_s`、证明字节数、各子进程退出码和 `verified`。并保存单证明者的独立对照时间以及该次对照对应的 statement 摘要。

`setup.jsonl` 记录 Setup、首次总时间、SRS 来源及是否复用、约束数、私有输入数、制品大小、工具版本。`summary.json` 对每项时间记录 `n/mean/stdev/median/min/max`。若某模型存在失败，写明计划次数、成功次数、失败原因；不无声排除失败运行并声称全部成功。

所有数值从这些文件自动生成。旧表数据不作为缺失值的补充；`export-results` 当前的 placeholder 导出器不能作为本任务结果来源。

## 9. LaTeX 表格模板

下面的 `TBD` 由导出器替换，时间和大小均不得手填。

### Table 1

```latex
\begin{table}[t]
\centering
\caption{System-level end-to-end efficiency of BlindCert with three MPC parties and three collaborative provers.}
\label{tab:baseline-performance}
\small
\begin{tabular}{lrrr}
\hline
Model & Setup (s) & End-to-end (s) & First-use total (s) \\
\hline
LR-D8 & TBD & TBD & TBD \\
LR-D16 & TBD & TBD & TBD \\
LR-D64 & TBD & TBD & TBD \\
MLP-D16-H8 & TBD & TBD & TBD \\
MLP-D16-H8,4 & TBD & TBD & TBD \\
polynomial SVM-D16,2 & TBD & TBD & TBD \\
LR-D256 & TBD & TBD & TBD \\
LR-D1024 & TBD & TBD & TBD \\
MLP-D128-H64 & TBD & TBD & TBD \\
MLP-D256-H128,64 & TBD & TBD & TBD \\
\hline
\end{tabular}
\end{table}
```

在表注中补充：会话时间是五次实测的均值与标准差；Setup 和首次总时间各为一次实测；精确定义见实验设置。若与当前模板列宽不符，调整字号/间距，保持这四列的含义。

### Table 2

```latex
\begin{table}[t]
\centering
\caption{Performance for certification relations of increasing model size.}
\label{tab:larger-relations}
\small
\setlength{\tabcolsep}{3pt}
\begin{tabular}{lrrrrrrr}
\hline
Model &
Constraints &
\shortstack[r]{Private\\inputs} &
\shortstack[r]{Single prove\\(s)} &
\shortstack[r]{Co-witness\\(s)} &
\shortstack[r]{Co-prove\\(s)} &
\shortstack[r]{verify\\(s)} &
\shortstack[r]{Proof size\\(KB)}\\
\hline
LR-D8 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
LR-D16 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
LR-D64 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
MLP-D16-H8 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
MLP-D16-H8,4 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
polynomial SVM-D16,2 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
LR-D256 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
LR-D1024 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
MLP-D128-H64 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
MLP-D256-H128,64 & TBD & TBD & TBD & TBD & TBD & TBD & TBD \\
\hline
\end{tabular}
\end{table}
```

保留两个原有表格标签，后续将这两个文件接入论文时复用现有交叉引用。性能结论根据实测曲线撰写；Groth16 的简洁性不能用于推导证明生成时间与模型规模无关。

## 10. 交付与 GitHub 上传

交付内容为：真实三方端到端实现、十个模型的电路/生成器及配置、自动化测量与导出脚本、正常路径验收结果、完整原始日志、两个 LaTeX 表格和 Ubuntu 复现说明。

注意源码不要有任何注释，尤其是中文注释。

提交源码、配置和可公开的结果摘要；私有输入、完整见证、参与方份额、凭据、节点私钥和大型生成制品不提交。检查已有 `.gitignore`，用文件清单显式暂存；本地保留需要审计的测量日志和制品摘要。

```bash
git diff --check
git status --short
# 按实际修改文件逐项 git add，再检查暂存差异。
git diff --cached --stat
git diff --cached
git commit -m "Implement three-party end-to-end efficiency benchmarks"
git push -u origin experiment/system-e2e-three-party
```

完成后报告实际分支、提交、成功/未完成的模型、固定工作负载配置和结果文件路径。若关键份额交接仍未实现，明确记录实现阻塞，先完成该连接，再产生系统端到端结果。

## 参考代码与接口文档

- [当前会话入口](https://github.com/ijaden/Blindcert/blob/0e480001c8712e4d96bd5216ee76b038acf895a4/blindcert/session.py)
- [MP-SPDZ 适配器](https://github.com/ijaden/Blindcert/blob/0e480001c8712e4d96bd5216ee76b038acf895a4/blindcert/mpc/mpspdz_backend.py)
- [现有组件计时脚本](https://github.com/ijaden/Blindcert/blob/0e480001c8712e4d96bd5216ee76b038acf895a4/scripts/run_efficiency_benchmark.py)
- [现有模型扩展脚本](https://github.com/ijaden/Blindcert/blob/0e480001c8712e4d96bd5216ee76b038acf895a4/scripts/run_larger_model_experiments.py)
- [协作证明与验证适配器](https://github.com/ijaden/Blindcert/blob/0e480001c8712e4d96bd5216ee76b038acf895a4/blindcert/proofs/collaborative_backend.py)
- [MP-SPDZ 官方份额输入/输出文档](https://mp-spdz.readthedocs.io/en/latest/io.html)：文件格式依协议而定，MAC 与有限域表示需要正确解析。
