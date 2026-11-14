import math,time,heapq,bisect
from src.services.geo import distance_matrix

SOLVER_TIME_LIMIT_S=30.0
REASON_NO_CANDIDATE='no_candidate_in_radius'
REASON_DEMAND='demand_exceeds_capacity'
REASON_NOT_SELECTED='site_not_selected'
REASON_CAPACITY='capacity_exhausted'
REASON_LABELS={REASON_NO_CANDIDATE:'半径内无候选点',REASON_DEMAND:'需求超过半径内候选日容量',REASON_NOT_SELECTED:'半径内候选点均未入选',REASON_CAPACITY:'入选点剩余容量不足'}
_EPS=1e-9

class _TimeUp(Exception):pass

def capacitated_coverage(points,candidates,radius_km,budget,max_sites,time_limit=SOLVER_TIME_LIMIT_S):
    """容量约束补给推演。每个样点整份需求由一处半径内已选点承担,站点不超载,
    预算与点数上限内最大化已服务权重。限时time_limit秒(硬上限SOLVER_TIME_LIMIT_S):
    超时返回当前最优可行解与有效收益上界;仅当上下界闭合时optimal_proven为真。"""
    start=time.monotonic()
    limit=max(1.0,min(float(time_limit),SOLVER_TIME_LIMIT_S))
    solver=_Solver(points,candidates,radius_km,budget,max_sites,start,limit)
    try:
        solver.greedy_construct()
        solver.polish_assignment()
        solver.improve()
    except _TimeUp:pass
    solver.ensure_assignment()
    try:solver.branch_and_bound()
    except _TimeUp:pass
    try:solver.sensitivity()
    except _TimeUp:solver.sens=[]
    return solver.build_result()

class _Solver:
    def __init__(self,points,candidates,radius_km,budget,max_sites,start,limit):
        # ---- 输入校验(与加权覆盖同口径,另加需求与容量) ----
        if not points or not candidates:raise ValueError('需求点与候选点不能为空')
        if len(candidates)>100 or len(points)>5000:raise ValueError('最多100候选点/5000需求点')
        if not math.isfinite(radius_km) or radius_km<=0 or not math.isfinite(budget) or budget<0 or not isinstance(max_sites,int) or max_sites<1:raise ValueError('半径、预算或数量限制无效')
        if len({p['site_id'] for p in points})!=len(points) or len({c['id'] for c in candidates})!=len(candidates):raise ValueError('需求点/候选点编号必须唯一')
        weights=[p['weight'] for p in points]
        if any(not math.isfinite(w) or w<0 for w in weights) or sum(weights)<=0:raise ValueError('权重必须非负且总权重大于0')
        if any(not math.isfinite(c['cost']) or c['cost']<=0 for c in candidates):raise ValueError('候选建设成本必须是正有限数')
        demands=[p.get('demand',1.0) for p in points]
        if any(isinstance(d,bool) or not isinstance(d,(int,float)) or not math.isfinite(d) or d<=0 for d in demands):raise ValueError('样点日需求量必须是正的有限数')
        if any(isinstance(c.get('daily_capacity'),bool) or not isinstance(c.get('daily_capacity'),(int,float)) or not math.isfinite(c['daily_capacity']) or c['daily_capacity']<=0 for c in candidates):raise ValueError('容量推演要求每个候选点录入正的日容量')
        self.points=points;self.candidates=sorted(candidates,key=lambda c:c['id'])
        self.radius=radius_km;self.budget=budget;self.max_sites=max_sites
        self.weights=weights;self.demands=demands
        self.caps=[c['daily_capacity'] for c in self.candidates]
        self.costs=[c['cost'] for c in self.candidates]
        self.n=len(self.candidates);self.m=len(points)
        self.total=sum(weights);self.total_demand=sum(demands)
        self.start=start;self.limit=limit
        self.solve_deadline=start+limit-max(1.0,0.05*limit)  # 求解截止,余量留给敏感性与装配
        self.hard_deadline=start+limit-0.45                  # 硬截止,余量留给结果装配
        # ---- 距离与半径可达集 ----
        self.dist=distance_matrix(points,self.candidates)
        self.order=sorted(range(self.m),key=lambda j:(-weights[j]/demands[j],-weights[j],points[j]['site_id']))
        self.elig=[[] for _ in range(self.n)]
        self.point_elig=[[] for _ in range(self.m)]
        for i in range(self.n):
            row=self.dist[i];own=[]
            for j in range(self.m):
                if row[j]<=radius_km+_EPS:own.append(j);self.point_elig[j].append(i)
            s=set(own);self.elig[i]=[j for j in self.order if j in s]
        self.reachable=sum(weights[j] for j in range(self.m) if self.point_elig[j])
        # ---- 每候选静态分数背包价值(上界与排序用) ----
        self.vstat=[self._frac_pack(self.elig[i],self.caps[i]) for i in range(self.n)]
        self.ratio_order=sorted(range(self.n),key=lambda i:(-self.vstat[i]/self.costs[i],self.candidates[i]['id']))
        ub_budget=0.0;rem=budget
        for i in self.ratio_order:
            if self.costs[i]<=rem+_EPS:ub_budget+=self.vstat[i];rem-=self.costs[i]
            else:ub_budget+=self.vstat[i]*rem/self.costs[i];break
        ub_count=sum(sorted((self.vstat[i] for i in range(self.n) if self.costs[i]<=budget+_EPS),reverse=True)[:max_sites])
        self.static_ub=min(self.total,self.reachable,ub_budget,ub_count)
        # ---- 求解状态 ----
        self.chosen=[];self.best_w=0.0;self.best_t=[-1]*self.m
        self.steps=[];self.sens=[];self.nodes=0
        self.proven=False;self.ub=self.static_ub

    def _frac_pack(self,own,cap):
        v=0.0;rem=cap
        for j in own:
            dj=self.demands[j]
            if dj<=rem+_EPS:v+=self.weights[j];rem-=dj
            else:v+=self.weights[j]*rem/dj;break
        return v

    def check(self,deadline=None):
        if time.monotonic()>(deadline or self.solve_deadline):raise _TimeUp()

    # ---- 固定选点集的整份分配:variant 0按权重/1按比值/2按需求量,最差适配或最佳适配 ----
    def assign(self,sel,variant=0):
        weights=self.weights;demands=self.demands;point_elig=self.point_elig
        rem=[-1.0]*self.n
        for i in sel:rem[i]=self.caps[i]
        if variant==0:seq=sorted(range(self.m),key=lambda j:(-weights[j],demands[j],self.points[j]['site_id']))
        elif variant==1:seq=self.order
        else:seq=sorted(range(self.m),key=lambda j:(demands[j],-weights[j],self.points[j]['site_id']))
        target=[-1]*self.m
        for j in seq:
            dj=demands[j];best=-1;best_rem=-1.0
            for i in point_elig[j]:
                r=rem[i]
                if r<dj-_EPS:continue
                if variant==2:
                    if best<0 or r<best_rem:best,best_rem=i,r
                elif r>best_rem:best,best_rem=i,r
            if best>=0:target[j]=best;rem[best]-=dj
        return sum(weights[j] for j in range(self.m) if target[j]>=0),target

    def assign_full(self,sel):
        best_w,best_t=-1.0,None
        for variant in (0,1,2):
            self.check()
            w,t=self.assign(sel,variant)
            if w>best_w+_EPS:best_w,best_t=w,t
        return best_w,best_t

    # ---- 阶段一:懒惰贪心构造(上界键值堆,失效重算) ----
    def greedy_construct(self):
        weights=self.weights;demands=self.demands
        covered=bytearray(self.m);spent=0.0;chosen_set=set()
        def gain(i):
            rem=self.caps[i];g=0.0
            for j in self.elig[i]:
                if covered[j]:continue
                dj=demands[j]
                if dj<=rem+_EPS:g+=weights[j];rem-=dj
            return g
        heap=[(-self.vstat[i]/self.costs[i],i) for i in range(self.n) if self.costs[i]<=self.budget+_EPS]
        heapq.heapify(heap)
        while heap and len(self.chosen)<self.max_sites:
            self.check()
            _,i=heapq.heappop(heap)
            if i in chosen_set or spent+self.costs[i]>self.budget+_EPS:continue
            g=gain(i);key=g/self.costs[i]
            if heap and key<-heap[0][0]-1e-12:heapq.heappush(heap,(-key,i));continue
            if g<=1e-12:break
            self.chosen.append(i);chosen_set.add(i);spent+=self.costs[i]
            rem=self.caps[i]
            for j in self.elig[i]:
                if covered[j]:continue
                if demands[j]<=rem+_EPS:covered[j]=1;rem-=demands[j]
            self.steps.append({'candidate_id':self.candidates[i]['id'],'name':self.candidates[i]['name'],'cost':self.costs[i]})

    def polish_assignment(self):
        if not self.chosen:return
        w,t=self.assign_full(self.chosen)
        if w>self.best_w+_EPS:self.best_w,self.best_t=w,t

    # ---- 阶段二:增点与1换1局部改进 ----
    def improve(self):
        improve_deadline=self.start+0.6*(self.solve_deadline-self.start)
        chosen_set=set(self.chosen);spent=sum(self.costs[i] for i in self.chosen)
        for _ in range(14):
            self.check(improve_deadline);improved=False
            best_add=None
            if len(self.chosen)<self.max_sites:
                for i in range(self.n):
                    if i in chosen_set or spent+self.costs[i]>self.budget+_EPS:continue
                    rem=self.caps[i];g=0.0
                    for j in self.elig[i]:
                        if self.best_t[j]>=0:continue
                        dj=self.demands[j]
                        if dj<=rem+_EPS:g+=self.weights[j];rem-=dj
                    if g>1e-9 and (best_add is None or g/self.costs[i]>best_add[0]):best_add=(g/self.costs[i],i)
            if best_add is not None:
                i=best_add[1];trial=self.chosen+[i]
                w,t=self.assign_full(trial)
                if w>self.best_w+_EPS:
                    self.chosen=trial;chosen_set.add(i);spent+=self.costs[i];self.best_w,self.best_t=w,t
                    self.steps.append({'candidate_id':self.candidates[i]['id'],'name':self.candidates[i]['name'],'cost':self.costs[i]});improved=True
            if not improved and self.chosen:
                load={i:0.0 for i in self.chosen}
                for j in range(self.m):
                    if self.best_t[j]>=0:load[self.best_t[j]]+=self.weights[j]
                outs=sorted(self.chosen,key=lambda i:load[i])[:3]
                ins=sorted((i for i in range(self.n) if i not in chosen_set),key=lambda i:-self.vstat[i])[:4]
                for o in outs:
                    for i in ins:
                        self.check(improve_deadline)
                        if spent-self.costs[o]+self.costs[i]>self.budget+_EPS:continue
                        trial=[x for x in self.chosen if x!=o]+[i]
                        w,t=self.assign(trial,0)
                        if w>self.best_w+_EPS:
                            w,t=self.assign_full(trial)
                            self.chosen=trial;chosen_set=set(trial);spent=sum(self.costs[x] for x in trial)
                            self.best_w,self.best_t=w,t;self.steps=None;improved=True;break
                    if improved:break
            if not improved:break

    def ensure_assignment(self):
        # 限时中断兜底:保证当前选点集至少有一次快速分配
        if self.chosen and self.best_w<=_EPS:
            try:
                self.check(self.hard_deadline-0.3)
                w,t=self.assign(self.chosen,0)
                if w>self.best_w+_EPS:self.best_w,self.best_t=w,t
            except _TimeUp:pass

    # ---- 阶段三:限时分支定界。界=已选静态价值和+剩余分数背包/点数上界,恒为有效上界 ----
    def branch_and_bound(self):
        n=self.n;budget=self.budget;max_sites=self.max_sites
        V=[self.vstat[i] for i in self.ratio_order];C=[self.costs[i] for i in self.ratio_order]
        orig=self.ratio_order
        sufC=[None]*(n+1);sufV=[None]*(n+1);sufTop=[None]*(n+1)
        sufC[n]=[0.0];sufV[n]=[0.0];sufTop[n]=[0.0]
        for j in range(n-1,-1,-1):
            pc=[0.0];pv=[0.0]
            for k in range(j,n):pc.append(pc[-1]+C[k]);pv.append(pv[-1]+V[k])
            sufC[j]=pc;sufV[j]=pv
            s=[0.0]
            for v in sorted(V[j:],reverse=True):s.append(s[-1]+v)
            sufTop[j]=s
        sufMin=[math.inf]*(n+1)
        for j in range(n-1,-1,-1):sufMin[j]=min(C[j],sufMin[j+1])
        def frac_bound(j,b):
            if b<=0:return 0.0
            pc=sufC[j];t=bisect.bisect_right(pc,b+1e-12)-1
            v=sufV[j][t]
            if t<len(pc)-1:
                idx=j+t
                if C[idx]>_EPS:v+=(b-pc[t])*V[idx]/C[idx]
            return v
        def topk_bound(j,k):
            s=sufTop[j];return s[min(k,len(s)-1)]
        def node_ub(j,spent,cnt,wbound):
            inner=min(frac_bound(j,budget-spent),topk_bound(j,max_sites-cnt))
            return min(wbound+inner,self.reachable)
        incumbent=self.best_w
        evaluated=set();leaf_evals=0;max_leaf=25 if self.n*self.m>200000 else 120
        stack=[(0,0.0,0,0.0,0,0)];uid_gen=0
        deferred=[(-node_ub(0,0.0,0,0.0),0)];live={0}
        while stack:
            self.nodes+=1
            if self.nodes&1023==0:self.check()
            if self.nodes>60_000_000:break
            j,spent,cnt,wbound,mask,uid=stack.pop()
            live.discard(uid)
            ub=node_ub(j,spent,cnt,wbound)
            if ub<=incumbent+1e-9:continue
            # 叶子特征:点数已满或剩余候选均超预算 → 评估实际分配,更新下界
            if (cnt==max_sites or j==n or sufMin[j]>budget-spent+_EPS) and mask and mask not in evaluated and leaf_evals<max_leaf:
                evaluated.add(mask);leaf_evals+=1;self.check()
                sel=[orig[k] for k in range(n) if mask>>k&1]
                w,t=self.assign(sel,0)
                if w>incumbent+1e-9:
                    incumbent=w;self.best_w=w;self.best_t=t
                    self.chosen=sel;self.steps=None
            if j==n:continue
            children=[]
            if spent+C[j]<=budget+_EPS and cnt<max_sites:
                children.append((j+1,spent+C[j],cnt+1,wbound+V[j],mask|(1<<j)))
            children.append((j+1,spent,cnt,wbound,mask))
            for cj,cs,cc,cw,cm in children:
                cub=node_ub(cj,cs,cc,cw)
                if cub<=incumbent+1e-9:continue
                uid_gen+=1;stack.append((cj,cs,cc,cw,cm,uid_gen))
                heapq.heappush(deferred,(-cub,uid_gen));live.add(uid_gen)
        if not stack:
            self.proven=True;self.ub=incumbent
        else:
            open_ub=incumbent
            while deferred:
                neg,uid=deferred[0]
                if uid not in live:heapq.heappop(deferred);continue
                open_ub=max(open_ub,-neg);break
            self.ub=min(self.static_ub,open_ub)
            if incumbent>=self.ub-1e-9:self.proven=True;self.ub=incumbent

    # ---- 阶段四:移除敏感性。固定其余选点,被移除点的样点贪心重安置,不重新优化 ----
    def sensitivity(self):
        deadline=self.hard_deadline-0.35
        load=[0.0]*self.n
        for j in range(self.m):
            if self.best_t[j]>=0:load[self.best_t[j]]+=self.demands[j]
        sens=[]
        for i in self.chosen:
            self.check(deadline)
            others={k:self.caps[k]-load[k] for k in self.chosen if k!=i}  # 其余选点剩余容量
            lost=0.0
            own=[j for j in range(self.m) if self.best_t[j]==i]
            own.sort(key=lambda j:(-self.weights[j],self.demands[j]))
            for j in own:
                dj=self.demands[j];best=-1;best_rem=-1.0
                for k in self.point_elig[j]:
                    r=others.get(k)
                    if r is None or r<dj-_EPS:continue
                    if r>best_rem:best,best_rem=k,r
                if best>=0:others[best]-=dj
                else:lost+=self.weights[j]
            sens.append({'candidate_id':self.candidates[i]['id'],'name':self.candidates[i]['name'],'unique_weight':lost,'coverage_rate_without':(self.best_w-lost)/self.total})
        self.sens=sens

    # ---- 结果装配:分配明细、余量、未服务原因、求解状态与对账 ----
    def build_result(self):
        chosen=self.chosen;sel_set=set(chosen)
        spent=sum(self.costs[i] for i in chosen)
        assigned_demand=[0.0]*self.n;assigned_weight=[0.0]*self.n;site_count=[0]*self.n
        for j in range(self.m):
            i=self.best_t[j]
            if i>=0:assigned_demand[i]+=self.demands[j];assigned_weight[i]+=self.weights[j];site_count[i]+=1
        served_weight=self.best_w;served_pts=sum(1 for t in self.best_t if t>=0)
        # 步骤按最终口径回放:增益=该点最终承担权重,与汇总及分配明细一致;选点集与记录不一致时按比值序重建
        by_id={c['id']:x for x,c in enumerate(self.candidates)}
        chosen_ids={self.candidates[i]['id'] for i in chosen}
        if not self.steps or {s['candidate_id'] for s in self.steps}!=chosen_ids:
            step_idx=[i for i in self.ratio_order if i in sel_set]
        else:step_idx=[by_id[s['candidate_id']] for s in self.steps]
        final_steps=[];cum=0.0;cum_cost=0.0
        for k,idx in enumerate(step_idx):
            c=self.candidates[idx];cum+=assigned_weight[idx];cum_cost+=self.costs[idx]
            final_steps.append({'step':k+1,'candidate_id':c['id'],'name':c['name'],'cost':self.costs[idx],'gain_weight':assigned_weight[idx],'covered_weight':cum,'coverage_rate':cum/self.total,'spent':cum_cost})
        mapped=[];reason_stat={}
        for j,p in enumerate(self.points):
            i=self.best_t[j]
            if i>=0:
                mapped.append({**p,'demand':self.demands[j],'covered':True,'served':True,'assigned_candidate_id':self.candidates[i]['id'],'assigned_distance_km':self.dist[i][j],'nearest_selected_km':self.dist[i][j],'unserved_reason':None})
            else:
                if not self.point_elig[j]:reason=REASON_NO_CANDIDATE
                elif self.demands[j]>max(self.caps[x] for x in self.point_elig[j])+_EPS:reason=REASON_DEMAND
                elif not any(x in sel_set for x in self.point_elig[j]):reason=REASON_NOT_SELECTED
                else:reason=REASON_CAPACITY
                near=min((self.dist[x][j] for x in self.point_elig[j] if x in sel_set),default=None)
                mapped.append({**p,'demand':self.demands[j],'covered':False,'served':False,'assigned_candidate_id':None,'assigned_distance_km':None,'nearest_selected_km':near,'unserved_reason':reason})
                s=reason_stat.setdefault(reason,{'reason':reason,'label':REASON_LABELS[reason],'points':0,'weight':0.0});s['points']+=1;s['weight']+=self.weights[j]
        assignments=[{'site_id':self.points[j]['site_id'],'candidate_id':self.candidates[self.best_t[j]]['id'],'weight':self.weights[j],'demand':self.demands[j],'distance_km':self.dist[self.best_t[j]][j]} for j in range(self.m) if self.best_t[j]>=0]
        selected=[{**self.candidates[i],'assigned_demand':assigned_demand[i],'remaining_capacity':self.caps[i]-assigned_demand[i],'assigned_weight':assigned_weight[i],'served_points':site_count[i]} for i in chosen]
        # 对账:汇总口径与分配明细独立重算,约束逐条复核
        rec_assign_w=sum(a['weight'] for a in assignments);rec_assign_d=sum(a['demand'] for a in assignments)
        rec={'served_weight_summary':served_weight,'served_weight_from_assignments':rec_assign_w,
             'assigned_demand_summary':sum(assigned_demand),'assigned_demand_from_assignments':rec_assign_d,
             'capacity_violations':sum(1 for i in chosen if assigned_demand[i]>self.caps[i]+1e-6),
             'budget_ok':spent<=self.budget+1e-6,'count_ok':len(chosen)<=self.max_sites,
             'matches':abs(served_weight-rec_assign_w)<=1e-6 and abs(sum(assigned_demand)-rec_assign_d)<=1e-6}
        gap=max(0.0,self.ub-served_weight)
        return {'mode':'capacity','points':mapped,'candidates':self.candidates,
         'selected_ids':[self.candidates[i]['id'] for i in chosen],'selected':selected,'steps':final_steps,'sensitivity':self.sens,
         'assignments':assignments,'unserved_reasons':sorted(reason_stat.values(),key=lambda x:-x['weight']),
         'covered_weight':served_weight,'served_weight':served_weight,'total_weight':self.total,'coverage_rate':served_weight/self.total,
         'covered_points':served_pts,'served_points':served_pts,'uncovered_points':self.m-served_pts,
         'total_demand':self.total_demand,'assigned_demand':sum(assigned_demand),
         'spent':spent,'budget':self.budget,'radius_km':self.radius,'max_sites':self.max_sites,'distance_matrix_km':self.dist,
         'solver':{'status':'optimal' if self.proven else 'feasible','optimal_proven':self.proven,'upper_bound':self.ub,'gap':gap,
                   'gap_rate':gap/self.ub if self.ub>_EPS else 0.0,'elapsed_s':round(time.monotonic()-self.start,3),'time_limit_s':self.limit,'nodes':self.nodes},
         'reconciliation':rec}
