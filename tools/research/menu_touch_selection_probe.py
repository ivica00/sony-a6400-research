"""Compose the new C mod policy with ORIGINAL hit and selection on retained data.

Explicit pointer/thread fixtures; refresh is recorded, not executed. This is
not proof of physical routing, UI-thread origin or visible camera feedback.
"""
import json
from tools.research.active_menu_snapshot_probe import HW,ROOT,geometry
from tools.research.prepare_active_menu_control import model_path
from tools.research.setting_node_snapshot_probe import run
from tools.research.menu_touch_policy_host import Policy,Context,Event

def main():
    capture=json.loads((HW/'native-layout-resource-snapshot-pid1175.json').read_text())
    menu=next(int(r['address'],16) for r in capture['records'] if r['size']==0x186bc)
    page=model_path(capture,menu)[2]
    known={}
    for r in capture['records']:
        a=int(r['address'],16);known.update({a+i:v for i,v in enumerate(bytes.fromhex(r['data']))})
    world=json.loads((HW/'native-widget-worldpos-contracts.json').read_text())
    for r in world['additional']:
        a=int(r['address'],16)
        for i,v in enumerate(bytes.fromhex(r['data'])):
            if a+i in known and known[a+i]!=v:raise ValueError('Older geometry helper conflicts with current capture')
    points=[(320,150+50*i) for i in range(6)]+[(0,0),(320,174)]
    widgets=[menu+0x9350+i*0x1118 for i in range(6)]
    native,cache,fixes=geometry(capture['records'],widgets,points)
    if any(not row['returned'] for row in native):raise ValueError(native)
    for row,result in enumerate(native):
        if [x['hit'] for x in result['hit_results']] != [int(i==row) for i in range(6)]+[0,0]:raise ValueError('Original hit matrix differs')
    checks=[]
    for point_index,point in enumerate(points):
        selections=[];refreshes=[]
        def position(_user,_mouse,x,y):x[0]=point[0];y[0]=point[1];return 1
        def hit(_user,row,_x,_y):return native[row-1]['hit_results'][point_index]['hit']
        def select(_user,row):
            result=run('22setItemSelectedByIndex',row,snapshot=page);selections.append(result)
            if result['status']!=1 or result['selected_after']!=row:raise ValueError('Original selection differs')
            return result['status']
        def refresh(_user):refreshes.append('request recorded only')
        policy=Policy(position,hit,select,refresh)
        context=Context(1,menu,int(page['object'],16),1,149,149,6,page['selected'],0)
        press=policy.process(context,Event(5,0,0));release=policy.process(context,Event(6,0,0))
        if point_index==0:
            if (press,release)!=(1,3) or selections or refreshes:raise ValueError('Same-row handling differs')
        elif point_index<6:
            if (press,release)!=(1,2) or len(selections)!=1 or len(refreshes)!=1:raise ValueError('Tap composition differs')
        elif selections or refreshes or release!=0:raise ValueError('Outside tap selected a row')
        checks.append(dict(point=point,press=press,release=release,original_selection_calls=selections,refresh_requests=refreshes))
    report=dict(scope=__doc__,capture_sha256=capture['sha256'],native_hit_checks=48,original_hit_results=native,geometry_cache_writes=cache,stale_it_workarounds=fixes,checks=checks,physical_input_routing_proven=False,ui_thread_origin_proven=False,visible_refresh_proven=False)
    (ROOT/'artifacts/analysis/menu-touch-selection-composition-e0127.json').write_text(json.dumps(report,indent=2))
    print('C adapter +48 original hit checks +5 original row changes pass; refresh only recorded')
if __name__=='__main__':main()
