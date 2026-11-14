# 野渡巡护 · 补给点覆盖推演

为野渡湿地32人巡护队在有限预算内选择补给点，保留球面距离、覆盖权重和点位移除敏感性；容量推演进一步按样点日需求与站点日容量做整份分配，限时搜索并给出收益上界，让每个取舍可复核。

## 真实工作场景

巡护队原来在纸图上圈半径、用Excel加总样点，距离口径不一致、预算分配缺少量化依据、边缘需求常年漏覆。本工程接收上游模拟需求CSV与候选点勘测表，替代覆盖计算、预算推演及审批归档，下游队长据此安排现场踏勘。所有坐标/成本/需求为模拟，不包含真实敏感巡护路线。

六个核心实体：SiteDataset巡护需求、CandidateSite候选点、CoverageScenario预算方案、CoverageRun覆盖运行、DecisionReview决策复核、Report归档报告。六页：覆盖图册、巡护需求、候选点位、预算推演、覆盖与敏感性、决策归档。共享SurveyMap与CoverageSummary同时用于总览和运行结果。

## 启动

```sh
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

前端 http://localhost:18213 ，API http://localhost:19213/docs ，MySQL端口17713。恰好frontend/backend/worker/db/redis五服务全部健康检查。数据库、Redis、共享产物使用命名卷。清理演示数据：`docker compose down -v --remove-orphans`。

| 账号 | 角色 | 权限 |
|---|---|---|
| admin@yedu.test | admin / 决策复核人 | 所有实体、审批/退回、审计 |
| analyst@yedu.test | analyst / 空间分析员 | 导入需求、录入候选、方案、计算、提交复核和生成报告 |
| viewer@yedu.test | viewer / 巡护观察员 | 六实体只读，下载已批准报告 |

统一演示密码 `Patrol2026!`。JWT HS256、PBKDF2密码哈希、持久化审计、全局错误处理、队列10任务配额。登录失败401，越权写入403，重复审批409。示例密钥可经JWT_SECRET配置。

## 一天的工作剧本

1. 08:30 分析员登录，检查 `patrol_demands_202611.csv` 的180个需求点和需求权重、日需求量。
2. 08:35 核查经纬度单位及样点编号，确认四个湿地区域均有数据。
3. 08:45 对照24个候选点的十进制度坐标、1/2/3万元成本与日容量，补录踏勘候选。
4. 09:00 建立覆盖半径4.5km、预算9万元、最多6点的方案，可逐个排除不可用候选；需要核算供需时勾选容量推演。
5. 09:05 运行，Redis接收任务，独立worker计算距离矩阵、预算贪心选择与移除敏感性；容量推演再做整份分配与限时分支定界，结果持久化MySQL。
6. 09:10 查看仍未覆盖需求及每一步新增覆盖，比较移除某点后的独有覆盖损失；容量方案另看分配明细、站点余量、未服务原因与收益上界。
7. 09:20 提交复核，说明球面距离不含航道障碍；决策复核人批准或退回。
8. 09:30 生成归档报告，观察员下载CSV，交给队长用于现场勘察讨论。

## 两类计算与失败态

Haversine距离以地球平均半径6371.0088km计算。纬度/经度先转弧度，`a=sin²(Δφ/2)+cosφ₁cosφ₂sin²(Δλ/2)`，`d=2R atan2(√a,√(1-a))`。a截断至[0,1]防舍入溢出，自然支持跨±180°经线。点权重非负、总权重大于0，坐标有限且纬度[-90,90]/经度[-180,180]，成本为正有限数。最多5000需求点和100候选，CSV重复编号拒绝。

**加权覆盖（默认，旧方案口径不变）**按`距离≤半径`建立集合，在剩余预算与选点上限内，每次选择`新增覆盖权重/成本`最大点；同值先看新增权重，再按ID。零增益不选。覆盖集合逐步取并集，单次运行覆盖单调不降；启发式不保证全局最优，也不承诺跨不同预算/半径的方案结果单调。零预算输出空选址与零覆盖，避免除零。移除敏感性固定其余选点，重新求覆盖并集，报告该点独有覆盖权重及移除后覆盖率，不重新优化。

**容量推演（方案勾选capacity_mode）**在半径覆盖之上叠加供需约束：每个样点的整份日需求由一处半径内已选点承担（不可拆分），各已选点承担的日需求总和不超过其日容量，仍在预算与点数上限内最大化已服务样点权重。样点日需求经CSV可选`demand`列录入（缺省1.0，须为正有限数）；候选点日容量经`daily_capacity`录入，容量推演要求每个候选均有正的日容量，否则运行失败并指明原因。

容量求解为限时30秒的启发式+分支定界（backend/src/services/capacity.py）：懒惰贪心构造→多起点整份分配→增点/换点局部改进得到可行解，再以"已选点静态分数背包价值+剩余预算分数背包/点数上限"为界做DFS分支定界。界恒为有效收益上界。30秒内遍历完成或上下界闭合时标记`optimal`（已证最优）；超时降级为当前最优可行解，结果仍列出收益上界、绝对/相对差距与搜索节点数，状态为`feasible`，不标最优。移除敏感性固定其余选点，受影响样点按剩余容量贪心重安置，报告无法重新安置的权重，不重新优化。

结果含分配明细（样点→补给点）、各站点已分配/剩余容量、未服务原因（半径内无候选点/需求超过半径内候选日容量/半径内候选均未入选/入选点剩余容量不足）、逐步选点序列（按最终承担权重回放，与汇总一致）及对账块：服务权重汇总与分配明细独立重算比对，容量/预算/点数约束逐条复核。旧方案（无capacity_mode字段的历史记录）仍按加权覆盖原方式计算，结果字段与checksum口径不变。

两类结果均包括完整距离矩阵、选点序列、成本、覆盖/未覆盖样点、移除敏感性、输入SHA256与方法限制，写数据库并存共享产物卷。CSV与已批准的固定结果绑定，公式前缀文本做保护；容量推演报告另含求解状态、上界、差距、站点容量余量与逐样点分配/未服务原因。

SVG前端地图无外部地图服务，使用局部等距近似投影及等尺度圆圈，标注模拟背景与坐标示意；实际覆盖判断全部由后端球面距离完成。大范围/极地数据的图形投影不能作为测绘成果，距离表仍按球面计算。需要航道距离时应另行提供真实通行图，不把直线覆盖当实地可达性。

## 技术与目录

| 层 | 技术 |
|---|---|
| 前端 | Vue3.5 / TypeScript5.7 / Vite6 / Nginx1.28 |
| 后端 | Python3.12 / FastAPI / PyMySQL |
| 计算 | Python标准库球面几何、贪心覆盖与敏感性 |
| 存储与异步 | MySQL8.4、Redis7.4、独立Python worker |

`frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}` 与 `backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}` 分离职责，76个有实际职责源文件。各业务表使用VARCHAR主键和LONGTEXT JSON载荷，确保完整距离矩阵超过64KB时可持久化；迁移DDL在backend/migrations/001_initial.sql。建表使用MySQL GET_LOCK避免backend/worker首次初始化争用。

角色/运行/复核枚举：后端src/constants/enums.py；前端src/constants/enums.ts的roleLabels/statusLabels。地理常量后端src/constants/geometry.py，前端src/constants/enums.ts的earthRadiusKm；地图投影近似常量另见src/utils/mapProjection.ts。

Seed自然键insert-only，不覆盖用户修改；固定随机seed2204生成180需求点（含日需求）、24候选点（含日容量）及已完成加权覆盖/容量推演两套方案运行与复核、报告。SEED_DEMO=true启动自动seed，失败记录日志。演示数据与剧本一致。

环境：DATABASE_URL、REDIS_URL、JWT_SECRET、SEED_DEMO、TASK_MODE、ARTIFACT_DIR；端口与数据库口令见.env.example。后端本地开发：安装requirements.txt并配置已运行MySQL/Redis后，`uvicorn src.main:app --reload`。前端 `npm install && npm run dev`，Vite配置将/api转发localhost:19213。

## 已知边界

模拟成本不含地形、通行与用地约束。Redis BLPOP出队后worker强杀无自动重投，需要重新提交。JSON文本载荷未实现多人编辑乐观锁和迁移回滚；默认账号仅本地演示。加权覆盖贪心是解释性启发式，不保证全局最优。容量推演的分支定界在100候选/5000样点规模下通常无法30秒内闭合，此时报告可行解与收益上界差距；上界来自分数背包松弛，差距偏保守，不代表真实最优距离上界还有那么远。5000样点级运行结果（含完整距离矩阵与分配明细）单条可达10MB量级，运行列表接口按现有设计整体返回，数据量大时前端轮询会变重。

真实容器、HTTP、手算oracle、浏览器主流程与截图证据在批次test-artifacts/gb-2204，源码目录不含测试报告、截图或日志。

## License

MIT，见LICENSE。
