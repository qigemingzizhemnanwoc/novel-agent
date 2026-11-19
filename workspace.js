let currentProject = null, position = 0, selectedEnd = null, prefs = {}, working = false;
const node = (tag, text) => Object.assign(document.createElement(tag), {textContent:text});
function action(text, fn) {const b=node('button',text); b.onclick=()=>run(fn,b.closest("#peopleView")?"characterStatus":"writingStatus"); return b;}
async function run(fn, statusId="writingStatus") {
  if (working) return;
  working=true; busy(true); document.querySelectorAll('#characterPanel button,#writingPanel button,#openProject').forEach(b=>b.disabled=true);
  $('settingFile').disabled=true;
  try {await fn();} catch(e) {$(statusId).textContent=e.message;}
  finally {working=false;busy(false);document.querySelectorAll('#characterPanel button,#writingPanel button,#openProject').forEach(b=>b.disabled=false);$('settingFile').disabled=false;$('openProject').disabled=!$('projects').options.length;$('extractCharacter').disabled=!projectId;}
}
function credentials() {
  if (!projectId) throw Error('请先导入或打开作品。');
  return {project:projectId,model:$('model').value};
}
async function refreshProjects() {
  const result=await post('/projects',{}); prefs=result.preferences;renderDeletePreference();
  $('projects').replaceChildren();
  for(const item of result.projects) {const option=node('option',item.name);option.value=item.id;$('projects').append(option);}
  if(projectId&&result.projects.some(p=>p.id===projectId)) $('projects').value=projectId;
  $('openProject').disabled=!result.projects.length;$('deleteProject').disabled=!result.projects.length;$('renameProject').disabled=!result.projects.length;
}
async function loadWorkspace(id) {
  await resetMemory();
  const data=await post('/project/open',{project:id});
  projectId=id; currentProject=data; imported=true;
  pollIndex(id);
  previewText=data.sections.map(s=>s.text).join('\n');previewPage=0;preview();
  position=previewText.length; selectedEnd=null; resetPreviewNavigation();history=[];resetFloors();$('chat').textContent='';
  $('status').textContent=`已打开：${data.name} · ${Array.from(previewText).length.toLocaleString()} 字符 · 已保存在本地`;
  $('writingIdea').value='';$('adjustment').value='';$('characterStatus').textContent='输入人物姓名后，点击“提取资料”。';$('extractCharacter').disabled=false;
  renderWorkspace(data);await refreshProjects();busy(false);renderBookNavigation();showView('read');
}
function selectionPosition() {
  const selection=getSelection(); if(!selection.rangeCount || selection.isCollapsed)return;
  const range=selection.getRangeAt(0), previewNode=$('preview');
  if(!previewNode.contains(range.startContainer)||!previewNode.contains(range.endContainer))return;
  const prefix=document.createRange();prefix.selectNodeContents(previewNode);prefix.setEnd(range.endContainer,range.endOffset);
  selectedEnd=previewPage*20000+prefix.toString().length;
  $('confirmPosition').disabled=false;
  $('previewSelectionStatus').textContent='已选中：'+selection.toString().slice(-70)+'；点击确认，将从选中内容之后续写。';
}
document.addEventListener('selectionchange',selectionPosition);
function materials() {
  const selected=new Set([...$('materials').querySelectorAll('input:checked')].map(n=>n.value));
  $('materials').replaceChildren();
  $('positionLabel').textContent=position===previewText.length?'续写位置：文末':`续写位置：所选句子之后（位置 ${position}）`;$('positionExcerpt').textContent=previewText?'接续于：“'+previewText.slice(Math.max(0,position-70),position).trim()+'”':'';
  if(!currentProject)return;
  for(const item of [...currentProject.characters,...currentProject.settings]) {
    const automatic=Boolean(item.fields), accepted=!automatic||item.fields.some(f=>f.accepted);
    const allowed=accepted&&(!automatic||$('allowFuture').checked||item.scope_end<=position);
    const label=node('label','');label.style.display='block';
    const box=document.createElement('input');box.type='checkbox';box.value=item.id;box.disabled=!allowed;box.checked=allowed&&selected.has(item.id);
    label.append(box,document.createTextNode(item.name+(automatic?'（已审核人物卡）':'（外部人设，可能含后文）')+(!allowed?' · 当前范围不可用或尚未同意':'')));
    $('materials').append(label);
  }
}
function renderDeletePreference() {
  $('restoreDeleteWarning').disabled=!prefs.skip_delete_warning;
  $('deletePreferenceStatus').textContent=prefs.skip_delete_warning?'删除提醒已关闭：删除将直接执行。可随时恢复确认。':'删除提醒已开启：删除前会请你确认。';
}
$('restoreDeleteWarning').onclick=async()=>{
  $('restoreDeleteWarning').disabled=true;
  try {prefs=await post('/preferences',{skip_delete_warning:false});renderDeletePreference();}
  catch(e){$('deletePreferenceStatus').textContent='恢复失败：'+e.message;$('restoreDeleteWarning').disabled=false;}
};
async function deletion(description='这条资料或候选') {
  if(prefs.skip_delete_warning)return true;
  $('deleteTitle').textContent='确认删除'+description+'？';$('skipWarning').checked=false;$('deleteDialog').showModal();$('cancelDelete').focus();
  const confirmed=await new Promise(resolve=>{
    $('confirmDelete').onclick=()=>{$('deleteDialog').close();resolve(true);};
    $('cancelDelete').onclick=()=>{$('deleteDialog').close();resolve(false);};
    $('deleteDialog').oncancel=()=>resolve(false);
  });
  if(confirmed&&$('skipWarning').checked){prefs=await post('/preferences',{skip_delete_warning:true});renderDeletePreference();}
  return confirmed;
}
async function removeRecord(kind,id) {
  if(await deletion(({settings:'这份外部人设',inspirations:'这条灵感方案',drafts:'这份续写候选稿'})[kind]))renderWorkspace(await post('/record/delete',{project:projectId,kind,id}));
}
function useParameters(record) {
  position=record.position;$('allowFuture').checked=record.future;
  $('eventCheck').checked=Boolean(record.experiment);$('writingLength').value=record.length;$('writingIdea').value=record.idea;$('adjustment').value='';
  $('writingMode').value='draft';positionLocked=true;renderPreviewMarkers();materials();
  for(const box of $('materials').querySelectorAll('input'))box.checked=!box.disabled&&record.materials.includes(box.value);
}
function renderWorkspace(data) {
  currentProject=data;
  $('characters').replaceChildren();
  for(const card of data.characters) {
    const article=node('article','');article.append(node('strong',card.name));
    const present=new Set(card.fields.map(f=>f.label));
    for(const label of ['姓名／别名','性别','年龄／出生时间','出生地','身份','家庭情况'])if(!present.has(label))article.append(node('p',label+'：未说明／无已保留条目'));
    for(const field of card.fields) {
      const row=node('div','');row.append(node('p',`${field.label}：${field.value}${field.accepted?'（已同意）':'（待审核）'}`));
      const detail=node('details','');detail.append(node('summary','原文依据'),node('pre',field.place+'\n'+field.quote));row.append(detail);
      if(!field.accepted)row.append(action('同意',async()=>renderWorkspace(await post('/character/review',{project:projectId,card:card.id,field:field.id,accept:true}))));
      row.append(action('拒绝并删除',async()=>{if(await deletion(card.name+'的“'+field.label+'”条目'))renderWorkspace(await post('/character/review',{project:projectId,card:card.id,field:field.id,accept:false}));}));article.append(row);
    }
    $('characters').append(article);
  }
  $('settingsList').replaceChildren();
  for(const item of data.settings){const row=node('p',item.name+' ');row.append(action('删除',()=>removeRecord('settings',item.id)));$('settingsList').append(row);}
  for(const kind of ['inspirations','drafts']) {
    $(kind).replaceChildren();
    for(const item of data[kind]) {
      const article=node('article','');article.append(node('p',`位置 ${item.position} · ${item.future?'允许参考后文':'不看后文'}`),node('pre',item.text));
      if(kind==='drafts'){article.append(node('p',item.experiment?'事件整理实验：开启':'事件整理实验：关闭'));if(item.experiment){const detail=node('details','');detail.append(node('summary',`事件整理 · ${item.experiment.scope} · 额外 ${(item.experiment.elapsed_ms/1000).toFixed(1)} 秒`),node('pre',item.experiment.notes));article.append(detail);}}
      if(kind==='inspirations')article.append(action('一键续写',async()=>{useParameters(item);$('writingIdea').value=item.idea+'\n采用这个灵感：'+item.text;await generate();}));
      else article.append(action('重写',async()=>{useParameters(item);showView('write');$('writingMore').open=true;$('writingPanel').scrollIntoView();$('adjustment').focus();$('writingStatus').textContent='已恢复这份稿件的原文位置和要求。填写调整后点击生成，原稿会保留。';}));
      article.append(action('删除／不保留',()=>removeRecord(kind,item.id)));$(kind).append(article);
    }
  }
  materials();
}
async function generate() {
  const auth=credentials();$('writingStatus').textContent=$('eventCheck').checked&&$('writingMode').value==='draft'?'正在整理已发生事件，然后续写，请稍候……':'正在查阅原文并生成，请稍候……';
  const result=await post('/writing/generate',{...auth,event_check:$('eventCheck').checked,mode:$('writingMode').value,position,future:$('allowFuture').checked,length:Number($('writingLength').value),idea:$('writingIdea').value,adjustment:$('adjustment').value,materials:[...$('materials').querySelectorAll('input:checked')].map(n=>n.value)});
  renderWorkspace(result);$('writingStatus').textContent='已生成并保存。可保留或删除。';
}
$('openProject').onclick=()=>run(()=>loadWorkspace($('projects').value),'status');
$('useSelection').onclick=()=>{
  showView('read');$('originalPreview').open=true;
  $('originalPreview').scrollIntoView({block:'start'});
  $('previewSelectionStatus').textContent='请在下方原文选中一句话，再点击“确认选中位置”。';
};
$('confirmPosition').onclick=()=>{
  if(selectedEnd===null)return;
  position=selectedEnd;positionLocked=true;materials();renderPreviewMarkers();
  $('previewSelectionStatus').textContent='已锁定续写位置：选中内容之后（位置 '+position+'）。下方分隔线为续写起点。';
  $('confirmPosition').disabled=true;
  showView('write');
};
$('useEnd').onclick=()=>{position=previewText.length;positionLocked=false;selectedEnd=null;$('confirmPosition').disabled=true;materials();renderPreviewMarkers();$('previewSelectionStatus').textContent='已恢复从文末续写。';};
$('allowFuture').onchange=materials;
$('generateWriting').onclick=()=>run(generate);
$('extractCharacter').onclick=()=>run(async()=>{const auth=credentials();const name=$('characterName').value.trim();if(!name){$('characterName').focus();throw Error('请先输入要提取的人物姓名。');}$('characterStatus').textContent='正在提取人物资料，请稍候……';renderWorkspace(await post('/character/extract',{...auth,name}));$('characterStatus').textContent='资料已提取，请在下方逐条审核。';},'characterStatus');
$('settingFile').onchange=()=>run(async()=>{if(!projectId)throw Error('请先打开作品。');const file=$('settingFile').files[0];if(!file)return;const sections=await readSections(file);renderWorkspace(await post('/setting/add',{project:projectId,name:file.name,text:sections.map(s=>s.text).join('\n')}));$('settingFile').value='';},'characterStatus');
refreshProjects().catch(e=>{$('status').textContent='请重启新版后端：'+e.message;});

let positionLocked=false, previewHit=null;
function resetPreviewNavigation(){
  positionLocked=false;previewHit=null;$('previewMatches').replaceChildren();
  $('previewSearch').value='';$('previewSearchStatus').textContent='';renderPreviewMarkers();
  $('previewSelectionStatus').textContent='选中原文后，可确认续写位置。';$('confirmPosition').disabled=true;
}
function renderPreviewMarkers(){
  const start=previewPage*20000,text=previewText.slice(start,start+20000),end=start+text.length;
  const bounds=new Set([start,end]);
  if(positionLocked&&position>=start&&position<=end)bounds.add(position);
  if(previewHit){for(const n of previewHit)if(n>start&&n<end)bounds.add(n);}
  const points=[...bounds].sort((a,b)=>a-b);$('preview').replaceChildren();
  for(let i=0;i<points.length;i++){
    const a=points[i];
    if(positionLocked&&a===position){const marker=document.createElement('span');marker.id='continuationMarker';marker.setAttribute('aria-label','从这里开始续写');$('preview').append(marker);}
    if(i===points.length-1)break;
    const value=previewText.slice(a,points[i+1]);
    if(previewHit&&a>=previewHit[0]&&a<previewHit[1])$('preview').append(node('mark',value));
    else $('preview').append(document.createTextNode(value));
  }
}
document.addEventListener('previewRendered',()=>{selectedEnd=null;$('confirmPosition').disabled=true;renderPreviewMarkers();});
$('previewSearchForm').onsubmit=event=>{
  event.preventDefault();const term=$('previewSearch').value.trim();$('previewMatches').replaceChildren();previewHit=null;
  if(!term){$('previewSearchStatus').textContent='请输入关键词。';renderPreviewMarkers();return;}
  let count=0,index=previewText.indexOf(term);
  while(index!==-1){
    count++;
    if(count<=200){const at=index;const button=node('button',count+'. '+previewText.slice(Math.max(0,at-18),at+term.length+32).replace(/\s+/g,' '));
      button.type='button';button.onclick=()=>{previewHit=[at,at+term.length];previewPage=Math.floor(at/20000);preview();$('preview').querySelector('mark')?.scrollIntoView({block:'center'});};$('previewMatches').append(button);}
    index=previewText.indexOf(term,index+term.length);
  }
  $('previewSearchStatus').textContent='找到 '+count+' 处'+(count>200?'，显示前 200 处':'')+'；点击结果跳转。';renderPreviewMarkers();
};

for(const id of ['inspirationPrompt','draftPrompt'])$(id).oninput=()=>{$('promptStatus').textContent='有未保存的修改；生成仍使用上次保存的提示词。';};
$('savePrompts').onclick=async()=>{
  $('savePrompts').disabled=true;
  try{await post('/prompts/save',{inspiration:$('inspirationPrompt').value,draft:$('draftPrompt').value});$('promptStatus').textContent='已保存到本地，下次打开自动读取。';}
  catch(e){$('promptStatus').textContent='未保存：'+e.message;}
  finally{$('savePrompts').disabled=false;}
};
post('/prompts/get',{}).then(value=>{
  $('inspirationPrompt').value=value.inspiration;$('draftPrompt').value=value.draft;
  $('inspirationPrompt').disabled=false;$('draftPrompt').disabled=false;$('promptStatus').textContent='已读取本地提示词。';$('savePrompts').disabled=false;
}).catch(e=>{$('promptStatus').textContent='读取失败，请确认新版后端已启动：'+e.message;});

function showView(name) {
  if(!projectId&&['read','write','people'].includes(name))name='library';
  for(const key of ['read','write','people','library','settings'])$(key+'View').hidden=key!==name;
  for(const button of document.querySelectorAll('[data-view]')){
    if(button.dataset.view===name)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  window.scrollTo({top:0,behavior:'instant'});
}
for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>showView(button.dataset.view);
document.querySelector('.brand').onclick=e=>{e.preventDefault();showView('read');};
$('openLibrary').onclick=$('startLibrary').onclick=()=>showView('library');
$('openSettings').onclick=()=>showView('settings');
$('returnToOriginal').onclick=()=>{
  showView('read');$('originalPreview').open=true;
  previewPage=Math.floor(Math.max(0,position-1)/20000);preview();
  $('continuationMarker')?.scrollIntoView({block:'center'});
};
function renderBookNavigation(){
  $('bookName').textContent=currentProject.name;$('readerTitle').textContent=currentProject.name;$('emptyWelcome').hidden=true;
  $('sectionList').replaceChildren();let offset=0;
  for(const [index,section] of currentProject.sections.entries()){
    const at=offset;const button=node('button',section.place||section.title||('原文片段 '+(index+1)));
    button.onclick=()=>{
      showView('read');previewPage=Math.floor(at/20000);previewHit=[at,Math.min(at+80,previewText.length)];preview();
      for(const item of $('sectionList').children)item.removeAttribute('aria-current');button.setAttribute('aria-current','location');
      $('preview').querySelector('mark')?.scrollIntoView({block:'center'});
    };
    $('sectionList').append(button);offset+=section.text.length+1;
  }
}

$('deleteProject').onclick=async()=>{
  if(working||!$('projects').value)return;
  const id=$('projects').value,name=$('projects').selectedOptions[0].textContent;
  $('projectDeleteTitle').textContent='删除“'+name+'”？';$('projectDeleteDialog').showModal();$('cancelProjectDelete').focus();
  const confirmed=await new Promise(resolve=>{
    $('confirmProjectDelete').onclick=()=>{$('projectDeleteDialog').close();resolve(true);};
    $('cancelProjectDelete').onclick=()=>{$('projectDeleteDialog').close();resolve(false);};
    $('projectDeleteDialog').oncancel=()=>resolve(false);
  });
  if(!confirmed)return;
  await run(async()=>{
    $('deleteProject').disabled=true;
    try{const deleted=await post('/project/delete',{project:id});if(deleted.deleted!==id)throw Error('删除未确认，请重启本地服务后重试。');if(id===projectId){projectId=null;currentProject=null;imported=false;previewText='';previewPage=0;position=0;history=[];preview();resetFloors();for(const key of ['chat','characters','settingsList','drafts','inspirations','materials','sectionList'])$(key).replaceChildren();$('bookName').textContent='小说阅读与创作';$('readerTitle').textContent='原文阅读';$('emptyWelcome').hidden=false;$('indexStatus').textContent='';showView('library');}
      await refreshProjects();if([...$('projects').options].some(o=>o.value===id))throw Error('作品仍在列表中，请重启本地服务后重试。');$('status').textContent='已删除作品“'+name+'”，原始导入文件保留。';
    }finally{$('deleteProject').disabled=!$('projects').options.length;}
  },'status');
};
showView('library');

$('renameProject').onclick=()=>{if(working||!$('projects').value)return;$('renameInput').value=$('projects').selectedOptions[0].textContent;$('renameDialog').dataset.project=$('projects').value;$('renameStatus').textContent='';$('renameDialog').showModal();$('renameInput').focus();$('renameInput').select();};
$('cancelRename').onclick=()=>$('renameDialog').close();
$('renameForm').onsubmit=async event=>{event.preventDefault();const id=$('renameDialog').dataset.project,name=$('renameInput').value.trim();if(!name){$('renameStatus').textContent='请输入作品名称。';return;}$('saveRename').disabled=true;try{const result=await post('/project/rename',{project:id,name});if(result.id!==id||result.name!==name)throw Error('重命名未确认，请重启本地服务后重试。');if(id===projectId){currentProject.name=name;renderBookNavigation();}await refreshProjects();$('projects').value=id;$('status').textContent='作品已重命名为“'+name+'”。';$('renameDialog').close();}catch(e){$('renameStatus').textContent=e.message;}finally{$('saveRename').disabled=false;}};
function updateThemeButton(){const dark=document.documentElement.dataset.theme==='dark';$('themeToggle').textContent=dark?'浅色':'深色';$('themeToggle').setAttribute('aria-pressed',String(dark));}
$('themeToggle').onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('novel-theme',theme)}catch{}updateThemeButton();};updateThemeButton();
