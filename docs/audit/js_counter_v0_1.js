const fs = require('fs'),vm=require('vm');
const src=fs.readFileSync('/mnt/data/muse-audit/Muse-MultiStudio/app/static/app.js','utf8');
const code=src.slice(src.indexOf('function countBy('),src.indexOf('function renderGallery('));
const nodes={};const get=id=>nodes[id] ||= {textContent:'',innerHTML:'',value:'',style:{}};
const context={document:{getElementById:get},$:get, state:{jobs:[{id:1,project_id:1,state:'queued',prompt:'prompt1',account_name:'A',kind:'image',account_id:1},{id:2,project_id:2,state:'queued',prompt:'prompt2',account_name:'A',kind:'image',account_id:1}],project:2,engine:{active:0,workers:2,paused:true},filter:'all',selected:new Set()},esc:x=>String(x??'').replace(/&/g,'&amp;')};
vm.createContext(context);vm.runInContext(code,context);context.renderTasks();
console.log(JSON.stringify({project:2,visible_tasks:get('projectCount').textContent,all_counter:get('count-all').textContent,queued_counter:get('count-queued').textContent}));
if(get('count-queued').textContent!==2)process.exit(1);
