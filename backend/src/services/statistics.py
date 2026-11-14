import hashlib,json
from src.services.coverage import weighted_coverage
from src.services.capacity import capacitated_coverage,SOLVER_TIME_LIMIT_S

def analyze(points,candidates,radius_km=4.5,budget=9,max_sites=6,capacity_mode=False,time_limit=None):
 if capacity_mode:
  result=capacitated_coverage(points,candidates,radius_km,budget,max_sites,time_limit or SOLVER_TIME_LIMIT_S)
  result['limitations']=['球面直线距离不是道路/航道通行距离，地图仅局部示意','容量推演按整份需求分配：每个样点由一处半径内已选点承担，站点日容量不超载','限时30秒的分支定界搜索；超时返回当前最优可行解并给出收益上界与差距，未闭合不标最优','移除敏感性固定其余点位并贪心重安置受影响样点，不重新优化，也不表示因果效应','半径以km计；权重/日需求量为模拟巡护需求，成本为模拟万元，日容量为模拟补给能力']
 else:
  result=weighted_coverage(points,candidates,radius_km,budget,max_sites)
  result['limitations']=['球面直线距离不是道路/航道通行距离，地图仅局部示意','贪心按新增覆盖权重/成本排序，并列按增益再按ID确定，属于启发式，不保证全局最优','半径以km计；权重是模拟巡护需求，成本为模拟万元','移除敏感性固定其余点位，不重新优化，也不表示因果效应']
 payload={'points':points,'candidates':sorted(candidates,key=lambda c:c['id']),'radius_km':radius_km,'budget':budget,'max_sites':max_sites}
 if capacity_mode:payload['capacity_mode']=True
 result['checksum']=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
 return result
