from feishu_setup import setup,call,save
c=setup();tid=c['tables']['发布计划'];base={'base_token':c['base_token'],'table_id':tid}
views={'今日待发布':[['计划日期','==','Today'],['执行状态','intersects',['待执行']]],'按账号和频道查看':[],'已发布':[['执行状态','intersects',['已发布']]],'异常待处理':[['执行状态','intersects',['异常待处理','结果待核查']]],'缺素材':[['执行状态','intersects',['缺素材']]]}
for name,conditions in views.items():
 if not c['views'].get(name):
  existing=call('view-list',**base)['views'];v=next((v for v in existing if v['name']==name),None)
  d={'views':[v]} if v else call('view-create',**base,json={'name':name,'type':'grid'});print(name,flush=True)
  v=d['views'][0];c['views'][name]=v.get('id') or v.get('view_id');save(c)
 call('view-set-filter',**base,view_id=c['views'][name],json={'logic':'and','conditions':conditions})
 call('view-set-sort',**base,view_id=c['views'][name],json={'sort_config':[{'field':'计划顺序','desc':False}]})
 if name=='按账号和频道查看':call('view-set-group',**base,view_id=c['views'][name],json={'group_config':[{'field':'GM窗口','desc':False},{'field':'频道ID','desc':False}]})
