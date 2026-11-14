import csv,io
from fastapi import HTTPException
from src.models.entities import Report
from src.config.settings import ARTIFACT_DIR
from src.utils import repository as repo
from src.utils.identity import new_id,now

def safe_cell(value):return "'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value
def list_reports():return repo.all_rows('reports')
def create(data):
 run,review=repo.get('runs',data.run_id),repo.get('reviews',data.review_id)
 if review['status']!='approved' or review['run_id']!=run['id'] or run['status']!='completed':raise ValueError('报告必须引用该运行已通过的复核')
 report=repo.put('reports',Report(new_id('rpt'),data.run_id,data.review_id,data.title,now()))
 ARTIFACT_DIR.mkdir(parents=True,exist_ok=True);(ARTIFACT_DIR/(report['id']+'.csv')).write_text(download(report['id']),encoding='utf-8');return report
def download(id):
 report=repo.get('reports',id);run=repo.get('runs',report['run_id']);r=run['result']
 if repo.get('reviews',report['review_id'])['status']!='approved':raise HTTPException(403,'复核未通过')
 out=io.StringIO();w=csv.writer(out)
 if r.get('mode')=='capacity':
  s=r['solver']
  w.writerow(['report','mode','radius_km','budget','spent','served_weight','total_weight','service_rate','solver_status','optimal_proven','upper_bound','gap','elapsed_s','checksum'])
  w.writerow([safe_cell(report['title']),'capacity',r['radius_km'],r['budget'],r['spent'],r['served_weight'],r['total_weight'],r['coverage_rate'],s['status'],s['optimal_proven'],s['upper_bound'],s['gap'],s['elapsed_s'],r['checksum']])
  w.writerow([]);w.writerow(['selected_id','name','latitude','longitude','cost','daily_capacity','assigned_demand','remaining_capacity','assigned_weight','served_points','unique_weight','service_rate_without'])
  sens={x['candidate_id']:x for x in r['sensitivity']}
  for c in r['selected']:
   x=sens.get(c['id'],{})
   w.writerow([c['id'],safe_cell(c['name']),c['latitude'],c['longitude'],c['cost'],c['daily_capacity'],c['assigned_demand'],c['remaining_capacity'],c['assigned_weight'],c['served_points'],x.get('unique_weight',''),x.get('coverage_rate_without','')])
  w.writerow([]);w.writerow(['site_id','label','latitude','longitude','weight','demand','served','assigned_candidate_id','assigned_distance_km','unserved_reason'])
  for p in r['points']:w.writerow([safe_cell(p['site_id']),safe_cell(p['label']),p['latitude'],p['longitude'],p['weight'],p['demand'],p['served'],p['assigned_candidate_id'] or '',p['assigned_distance_km'] if p['assigned_distance_km'] is not None else '',p['unserved_reason'] or ''])
  return '\ufeff'+out.getvalue()
 w.writerow(['report','radius_km','budget','spent','coverage_rate','checksum']);w.writerow([safe_cell(report['title']),r['radius_km'],r['budget'],r['spent'],r['coverage_rate'],r['checksum']])
 w.writerow([]);w.writerow(['selected_id','name','latitude','longitude','cost','unique_weight','coverage_rate_without'])
 for c,s in zip(r['selected'],r['sensitivity']):w.writerow([c['id'],safe_cell(c['name']),c['latitude'],c['longitude'],c['cost'],s['unique_weight'],s['coverage_rate_without']])
 w.writerow([]);w.writerow(['site_id','label','latitude','longitude','weight','covered','nearest_selected_km'])
 for p in r['points']:w.writerow([safe_cell(p['site_id']),safe_cell(p['label']),p['latitude'],p['longitude'],p['weight'],p['covered'],p['nearest_selected_km']])
 return '\ufeff'+out.getvalue()
