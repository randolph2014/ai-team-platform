# AGENTS.md instructions

1. 回答用中文。
2. 从根本去解决问题。
3. 有歧义或疑问，一定让我决策，禁止私自乱改文件。
4. 所有的结论，一定要有充分的证据。
5. 遇到废弃代码，一定及时删除，不造成后续方案摇摆。
6. 简单需求，直接处理。不要对简单问题过度流程化。不要为了“展示流程”而增加复杂度。
7. 跨模块改动、架构调整、数据库结构变更、权限与安全逻辑、核心逻辑调整、高风险生产变更等复杂或重大影响的任务，必须进入规划模式。

## ai-team-platform 项目级最高约束

1. Harness Governance Layer 是项目级治理资产层，只能承载 rules、skills、checks、baselines、task memory；不能和 AGENTS、平台默认模板、agent prompt 覆盖或单次 pipeline config 混作同一个事实源。
2. AGENTS.md、平台安全策略、human gate、quality gate 的优先级高于 Harness 资产和项目 prompt；任何 Harness rule 或 skill 都不能绕过 human gate、quality gate 或 AGENTS.md。
3. Harness 配置真相源必须是仓库内 Harness 资产；不能把 DB 作为 Harness 配置真相源，DB 只能保存运行期设置、执行结果、审计或缓存。
4. Harness 子迭代必须按已确认阶段隔离推进；没有 fresh 测试、扫描或文件证据，不允许声明完成。
