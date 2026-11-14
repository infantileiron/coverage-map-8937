export const roleLabels:Record<string,string>={admin:'决策复核人',analyst:'空间分析员',viewer:'巡护观察员'};
export const statusLabels:Record<string,string>={queued:'排队中',running:'推演中',completed:'已完成',failed:'失败',pending:'待复核',approved:'已批准',rejected:'已退回'};
export const solverStatusLabels:Record<string,string>={optimal:'已证最优',feasible:'限时可行解'};
export const reasonLabels:Record<string,string>={no_candidate_in_radius:'半径内无候选点',demand_exceeds_capacity:'需求超过半径内候选日容量',site_not_selected:'半径内候选点均未入选',capacity_exhausted:'入选点剩余容量不足'};
export const earthRadiusKm=6371.0088;
