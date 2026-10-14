'use strict';
const $=id=>document.getElementById(id);
let unlocked=false,library='',pending=null,lastOutput='',busy=false;
async function api(path,data){
 const r=await fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,cache:'no-store'});
 const value=await r.json();
 if(!r.ok){if(r.status===401&&path!='/api/login')lock();throw Error(value.error||'Request failed');}return value;
}
function lock(){unlocked=false;$('console').hidden=true;$('login').hidden=false;$('logout').hidden=true;$('connection').textContent='LOCKED';$('lamp').className='';}
function unlock(){unlocked=true;$('console').hidden=false;$('login').hidden=true;$('logout').hidden=false;}
function message(text){$('message').textContent=text;}
async function press(key){try{await api('/api/key',{key});await refresh();}catch(e){message(e.message);}}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/login',{key:$('access-key').value.trim()});$('access-key').value='';$('login-error').textContent='';unlock();await refresh();}catch(err){$('login-error').textContent=err.message;}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{});}finally{lock();}});
document.querySelectorAll('[data-key]').forEach(b=>b.addEventListener('click',()=>press(b.dataset.key)));
document.addEventListener('keydown',e=>{if(!unlocked||$('run-dialog').open||['INPUT','TEXTAREA'].includes(e.target.tagName)||e.repeat)return;const keys={ArrowUp:'UP',ArrowDown:'DOWN',ArrowLeft:'LEFT',ArrowRight:'RIGHT',Enter:'OK',Escape:'KEY1','1':'KEY1','2':'KEY2','3':'KEY3'};if(keys[e.key]){e.preventDefault();press(keys[e.key]);}});
$('cancel-run').onclick=()=>$('run-dialog').close();
$('confirm-run').onclick=async()=>{if(!pending)return;try{await api('/api/run',{id:pending.id});$('run-dialog').close();message('');await refresh();}catch(e){message(e.message);$('run-dialog').close();}};
function drawScripts(scripts,sections){
 const signature=JSON.stringify([sections,scripts]);if(signature===library)return;library=signature;
 const host=$('scripts');host.replaceChildren();
 const groups=sections&&sections.length?sections:[{id:'general',name:'General',description:''}];
 let n=0;
 groups.forEach(section=>{const items=scripts.filter(s=>(s.section||'general')===section.id);if(!items.length)return;
  const heading=document.createElement('h3');heading.className='section-heading';heading.textContent=section.name;host.append(heading);
  items.forEach(script=>{n+=1;const card=document.createElement('article');card.className='script-card';const no=document.createElement('span');no.className='script-number';no.textContent=`RITUAL / ${String(n).padStart(2,'0')}`;const name=document.createElement('h3');name.textContent=script.name;const desc=document.createElement('p');desc.textContent=script.description;const button=document.createElement('button');button.textContent='Run ritual ↗';button.className='run-button';button.onclick=()=>{pending=script;$('run-name').textContent=script.name;$('run-description').textContent=script.description;$('run-dialog').showModal();};card.append(no,name,desc,button);host.append(card);});
 });
}
async function refresh(){
 if(!unlocked||busy)return;busy=true;
 try{const state=await api('/api/state'),s=state.stats;
 $('connection').textContent='CONNECTED';$('lamp').className='online';
 for(const id of ['cpu','memory','disk'])$(id).textContent=s[id]===undefined?'—':`${s[id]}%`;
 for(const id of ['cpu','memory'])$(id+'-bar').style.width=`${Math.min(100,Math.max(0,s[id]||0))}%`;
 $('temperature').textContent=s.temperature==null?'—':`${s.temperature}°C`;
 for(const id of ['uptime','hostname','tailscale','ssid','gateway'])$(id).textContent=s[id]||'—';
 $('tail-ip').textContent=s.tail_ip||'—';$('display-tag').textContent=state.display==='ST7789_240'?'240 × 240':'128 × 128';
 $('hardware-note').textContent=state.hardware?`DISPLAY ACTIVE / ${state.rotation}° / LAST INPUT: ${state.last_key}`:`DISPLAY UNAVAILABLE / ${state.hardware_error}`;
 drawScripts(state.scripts,state.sections);const running=['running','stopping'].includes(state.job.status);document.querySelectorAll('.run-button').forEach(b=>b.disabled=running);
 $('job-name').textContent=state.job.name;$('job-status').textContent=state.job.status.toUpperCase();
 const output=state.job.lines.join('\n')||'Your script output will appear here.';if(output!==lastOutput){const pre=$('output'),atEnd=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-30;pre.textContent=output;if(atEnd)pre.scrollTop=pre.scrollHeight;lastOutput=output;}
 $('screen').src='/api/frame?t='+Date.now();
 }catch(e){$('connection').textContent='DISCONNECTED';$('lamp').className='';if(unlocked)message(e.message);}finally{busy=false;}
}
(async()=>{try{await api('/api/state');unlock();await refresh();}catch{}setInterval(()=>{if(!document.hidden)refresh();},1000);})();
