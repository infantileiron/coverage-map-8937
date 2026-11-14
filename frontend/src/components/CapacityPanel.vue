<script setup lang="ts">
import {computed,ref} from 'vue';import type {CoverageResult} from '../types/entities';import {percent,number} from '../utils/format';import {solverStatusLabels} from '../constants/enums';
const props=defineProps<{result:CoverageResult}>();
const solver=computed(()=>props.result.solver!),rec=computed(()=>props.result.reconciliation!);
const showAssignments=ref(false);
const checks=computed(()=>[
 {label:'服务权重汇总 = 分配明细合计',ok:Math.abs(rec.value.served_weight_summary-rec.value.served_weight_from_assignments)<=1e-6,detail:`${number(rec.value.served_weight_summary)} = ${number(rec.value.served_weight_from_assignments)}`},
 {label:'分配需求汇总 = 分配明细合计',ok:Math.abs(rec.value.assigned_demand_summary-rec.value.assigned_demand_from_assignments)<=1e-6,detail:`${number(rec.value.assigned_demand_summary)} = ${number(rec.value.assigned_demand_from_assignments)}`},
 {label:'站点容量零超载',ok:rec.value.capacity_violations===0,detail:`${rec.value.capacity_violations} 处超载`},
 {label:'预算约束',ok:rec.value.budget_ok,detail:`已花 ${number(props.result.spent)} / ${props.result.budget} 万元`},
 {label:'点数上限',ok:rec.value.count_ok,detail:`已选 ${props.result.selected_ids.length} / ${props.result.max_sites} 点`}]);
</script>
<template>
<section class="paper">
 <h2>容量推演 · 求解状态</h2>
 <div class="solver-grid">
  <div><small>求解状态</small><span class="badge" :class="solver.optimal_proven?'completed':'pending'">{{solverStatusLabels[solver.status]||solver.status}}</span>
   <p v-if="!solver.optimal_proven" class="solver-note">搜索在 {{solver.time_limit_s}} 秒限时内未闭合上下界，返回当前最优可行解；不标记为最优。</p>
   <p v-else class="solver-note">分支定界已遍历全部搜索空间，上下界闭合，该方案为已证明的最优解。</p></div>
  <div><small>收益上界</small><strong>{{number(solver.upper_bound)}}</strong><span>任何方案都不可能超过的服务权重</span></div>
  <div><small>与上界差距</small><strong>{{number(solver.gap)}}<em>{{percent(solver.gap_rate)}}</em></strong><span>已服务 {{number(result.served_weight!)}} 权重</span></div>
  <div><small>求解用时</small><strong>{{solver.elapsed_s}}<em>秒</em></strong><span>限时 {{solver.time_limit_s}} 秒 · 搜索节点 {{solver.nodes}}</span></div>
 </div>
</section>
<section class="paper table-scroll">
 <h2>站点容量与余量</h2>
 <table><thead><tr><th>补给点</th><th>日容量</th><th>已分配需求</th><th>剩余容量</th><th>服务权重</th><th>服务样点</th></tr></thead>
 <tbody><tr v-for="c in result.selected" :key="c.id"><td><b>{{c.name}}</b><small>{{c.id}}</small></td><td>{{c.daily_capacity}}</td><td>{{number(c.assigned_demand!)}}</td><td>{{number(c.remaining_capacity!)}}</td><td>{{number(c.assigned_weight!)}}</td><td>{{c.served_points}}</td></tr></tbody></table>
 <small>需求总量 {{number(result.total_demand!)}} · 已分配 {{number(result.assigned_demand!)}} · 余量合计 {{number(result.selected.reduce((s,c)=>s+(c.remaining_capacity||0),0))}}</small>
</section>
<section class="paper table-scroll" v-if="result.unserved_reasons?.length">
 <h2>未服务样点原因</h2>
 <table><thead><tr><th>原因</th><th>样点数</th><th>未服务权重</th></tr></thead>
 <tbody><tr v-for="r in result.unserved_reasons" :key="r.reason"><td>{{r.label}}</td><td>{{r.points}}</td><td>{{number(r.weight)}}</td></tr></tbody></table>
</section>
<section class="paper">
 <h2>汇总与明细对账</h2>
 <ul class="recon-list"><li v-for="c in checks" :key="c.label"><span class="badge" :class="c.ok?'completed':'rejected'">{{c.ok?'一致':'异常'}}</span><div><b>{{c.label}}</b><small>{{c.detail}}</small></div></li></ul>
</section>
<section class="paper table-scroll">
 <h2 @click="showAssignments=!showAssignments" class="collapsible">{{showAssignments?'▾':'▸'}} 分配明细（{{result.assignments?.length||0}} 条）</h2>
 <table v-if="showAssignments"><thead><tr><th>样点</th><th>承担补给点</th><th>日需求</th><th>权重</th><th>距离 km</th></tr></thead>
 <tbody><tr v-for="a in result.assignments" :key="a.site_id"><td>{{a.site_id}}</td><td>{{a.candidate_id}}</td><td>{{a.demand}}</td><td>{{a.weight}}</td><td>{{a.distance_km.toFixed(2)}}</td></tr></tbody></table>
</section>
</template>
<style scoped>
.solver-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:23px}
.solver-grid strong{font-size:30px;font-weight:500;display:block;line-height:1.7}
.solver-grid strong em{font-style:normal;font-size:12px;margin-left:8px}
.solver-grid span{font-size:11px;color:oklch(49% .035 70)}
.solver-note{font-size:12px;margin:10px 0 0}
.recon-list{list-style:none;padding:0;margin:0}
.recon-list li{display:flex;gap:14px;align-items:center;padding:12px 0;border-bottom:1px solid oklch(84% .025 80)}
.recon-list li:last-child{border:0}
.recon-list b{font-size:13px;font-weight:500}
.collapsible{cursor:pointer;user-select:none}
</style>
