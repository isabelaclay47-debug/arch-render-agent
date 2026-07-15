const $ = id => document.getElementById(id);
let engine = "chat", pickedFile = null, imageDesc = "", lastPromptZh = "";
const PRESETS = [
  ["写实日景","照片级建筑写实日景：自然白天漫射光，柔和阴影，真实玻璃反射，材质细节清晰，专业建筑摄影后期，避免CG塑料感。"],
  ["黄金时刻","黄金时刻建筑摄影：低角度暖光，长阴影，玻璃暖冷反差，天空轻微渐变，氛围温暖但不过度电影化。"],
  ["玻璃幕墙","玻璃幕墙细节：低反射 Low-E 玻璃，室内暗部层次可见，竖梃横梁清晰，不做假蓝玻璃。"],
  ["石材立面","石材立面细节：浅米白或灰白石材，细微颗粒、分缝对齐、边缘倒角，避免塑料白墙。"],
  ["清水混凝土","清水混凝土质感：模板缝、拉片孔、微小色差、真实粗糙度，避免脏污过度。"],
  ["杂志摄影","建筑杂志摄影质感：等效35-50mm，竖线垂直，自然HDR，轻微景深，边缘锐利但不过度锐化。"],
  ["形体锁定","硬性约束：建筑形体、层数、开窗、柱网、屋顶线、场地必须与原图一致，不得增删移动。"],
  ["负向质量","负向约束：禁止过度锐化、强HDR、CG塑料感、假蓝玻璃、乱码文字、弯曲窗框、漂浮建筑。"],
];
$("presets").innerHTML = PRESETS.map(([n,t],i)=>
  `<label><input type="checkbox" value="${i}"><span>${n}</span></label>`).join("");

function setEngine(e){
  engine=e;
  $("engChat").classList.toggle("on",e==="chat");
  $("engLocal").classList.toggle("on",e==="local");
  $("engHint").textContent = e==="chat"
    ? "将用 ChatGPT 看图并扩写（需已启动专用 Chrome 并登录）。"
    : "将用本机 Ollama 视觉模型离线识图，免账号免 VPN。未装可在下方一键准备。";
  $("visionSetup").innerHTML="";
  resetConfirm();                    // 换引擎：清掉上一版理解，重新看图理解
  if(e==="local"){ refreshVisionStatus(); }
  checkNet();                        // VPN 安全版：chat 模式要网络才探测并提示，local 模式静默隐藏
}

// VPN 安全版：ChatGPT 模式静默探测 chatgpt.com 是否可达。能连→不打扰；连不上→提示条。
// local（离线识图）模式不需要网络，直接隐藏。
async function checkNet(userClicked){
  const banner=$("netBanner"); if(!banner) return;
  if(engine!=="chat"){ banner.style.display="none"; return; }
  try{
    const j=await (await fetch("/api/net_check?target=chatgpt")).json();
    banner.style.display = j.reachable ? "none" : "block";
  }catch(e){ if(userClicked) banner.style.display="block"; }
}

// 隐藏并清空「看图理解」确认区（换图/换引擎/重来时）
function resetConfirm(){
  const c=$("confirmCard"); if(c) c.classList.add("hidden");
  const u=$("understandEdit"); if(u) u.value="";
  const q=$("questionBox"); if(q) q.textContent="";
}

function onPick(f){
  if(!f) return; pickedFile=f; imageDesc="";
  $("dropHint").textContent="已选择图片（可点击重选，点图放大）";
  $("dropPrev").innerHTML=`<img src="${URL.createObjectURL(f)}" style="cursor:zoom-in"
        onclick="event.stopPropagation();zoom(this.src)">`;
  $("descBox").textContent="";
  $("toRenderBtn").style.display="block";        // 有图了才能发给渲染器
  resetConfirm();                                // 换了新图：清掉旧理解，重新看图理解
}

// ③ 把当前图发给渲染器当底图，跳转回主页自动接收
async function sendToRender(){
  if(!pickedFile){ alert("先选一张图"); return; }
  const fd=new FormData();
  fd.append("to","render");
  fd.append("image",pickedFile);
  const j=await (await fetch("/api/handoff",{method:"POST",body:fd})).json();
  if(!j.ok){ alert(j.msg||"发送失败"); return; }
  window.location="/";
}

// 页面加载时接收从渲染器发来的底图
async function receiveHandoff(){
  try{
    const r=await fetch("/api/handoff/helper");
    if(r.status!==200) return;
    const blob=await r.blob();
    onPick(new File([blob],"底图.jpg",{type:blob.type||"image/jpeg"}));
    await fetch("/api/handoff_clear",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({to:"helper"})});
  }catch(e){ /* 无待接收则忽略 */ }
}

// 拖拽
const drop=$("drop");
["dragenter","dragover"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add("dragover");}));
["dragleave","drop"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove("dragover");}));
drop.addEventListener("drop",e=>{const f=e.dataTransfer.files[0]; if(f&&f.type.startsWith("image/")) onPick(f);});

function selectedPresets(){
  return [...document.querySelectorAll("#presets input:checked")]
    .map(el=>window.I18N ? I18N.t(PRESETS[+el.value][1]) : PRESETS[+el.value][1]);
}

// ① 看图理解：先让 AI（按所选引擎）说出它看懂了什么，交给用户确认——不直接出提示词。
async function understand(){
  if(!pickedFile) return directGenerate();     // 没上传图 → 无需看图，直接按想法生成
  const box=$("understandEdit");
  $("confirmCard").classList.remove("hidden");
  box.value="AI 正在看图理解中（首次可能较慢）…"; $("questionBox").textContent="";
  const btn=event&&event.target; if(btn){ btn.disabled=true; }
  try{
    if(engine==="local"){
      const fd=new FormData(); fd.append("image",pickedFile);
      const j=await (await fetch("/api/helper_vision",{method:"POST",body:fd})).json();
      if(j.ok){ imageDesc=(j.desc||"").trim(); box.value=imageDesc||"";
                $("descBox").textContent="本地识图（"+j.model+"）完成，请在下方确认或修改。"; }
      else{ box.value=""; box.placeholder="本地识图暂不可用，可直接在这里手写画面描述后认可。";
            $("questionBox").textContent=j.msg||""; }
    }else{
      const fd=new FormData(); fd.append("image",pickedFile); fd.append("intent",$("intent").value.trim());
      const r=await fetch("/api/helper_understand",{method:"POST",body:fd});
      const j=await r.json();
      if(!j.ok){ box.value=""; $("questionBox").textContent=j.msg||"看图理解失败"; return; }
      box.value=(j.understanding_zh||"").trim();
      $("questionBox").textContent = (j.questions||"").trim() ? ("AI 想跟你确认：\n"+j.questions) : "";
    }
    $("confirmCard").scrollIntoView({behavior:"smooth",block:"nearest"});
  }catch(e){ box.value=""; $("questionBox").textContent="看图理解失败："+e.message; }
  finally{ if(btn){ btn.disabled=false; } }
}

// ② 认可后生成：以用户确认/修正过的理解为准绳，据此产出提示词（真正和底图挂钩）。
async function confirmGenerate(){
  const confirmed=$("understandEdit").value.trim();
  if(!confirmed){ alert("请先让 AI 看图理解，或在上面写一句这张图是什么，再认可"); return; }
  const intent=$("intent").value.trim(), presets=selectedPresets();
  const btn=event&&event.target; if(btn){ btn.disabled=true; btn.textContent="生成中…"; }
  try{
    if(engine==="local"){
      imageDesc=confirmed;                        // 认可后的理解 = 底图画面，驱动本地拼装
      const r=await fetch("/api/helper_build",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({intent,image_desc:confirmed,presets})});
      show(await r.json());
    }else{
      const fd=new FormData();
      fd.append("understanding",confirmed); fd.append("intent",intent);
      presets.forEach(p=>fd.append("presets",p));
      if(pickedFile) fd.append("image",pickedFile);
      const r=await fetch("/api/helper_generate",{method:"POST",body:fd});
      if(r.status>=400){ const j=await r.json(); alert(j.msg||"生成失败"); return; }
      show(await r.json());
    }
  }catch(e){ alert("生成失败："+e.message); }
  finally{ if(btn){ btn.disabled=false; btn.textContent="✓ 认可，据此生成提示词"; } }
}

// 没上传图时的直接生成（保留旧行为：纯按想法+储备库拼/扩写）
async function directGenerate(){
  const intent=$("intent").value.trim(), presets=selectedPresets();
  if(engine==="local"){
    const r=await fetch("/api/helper_build",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({intent,image_desc:"",presets})});
    show(await r.json());
  }else{
    const fd=new FormData();
    fd.append("draft_prompt",[intent,...presets].filter(Boolean).join("\n"));
    const r=await fetch("/api/helper_refine",{method:"POST",body:fd});
    if(r.status===409||r.status===400){ const j=await r.json(); alert(j.msg); return; }
    show(await r.json());
  }
}

function show(d){
  if(!d.ok && d.msg){ alert(d.msg); return; }
  $("result").classList.remove("hidden");
  $("understanding").textContent=d.understanding_zh||"";
  $("zh").textContent=d.prompt_zh||"";
  $("en").textContent=d.prompt_en||"";
  if(d.prompt_zh) lastPromptZh=d.prompt_zh;      // 记住供「改一版」在其基础上修订
  $("result").scrollIntoView({behavior:"smooth",block:"nearest"});
}
function copyEn(){ navigator.clipboard.writeText($("en").textContent).then(()=>alert("已复制英文提示词")); }

// 需求④：对提示词不满意 → 在上一版基础上按意见改，而不是从头再来
async function refinePrompt(){
  const fb=$("refineText").value.trim();
  if(!fb){ alert("先写一句你想怎么改"); return; }
  if(!lastPromptZh){ alert("请先生成一版提示词"); return; }
  const btn=event&&event.target; if(btn){ btn.disabled=true; btn.textContent="改稿中…"; }
  try{
    if(engine==="chat"){
      const fd=new FormData();
      fd.append("prev_zh",lastPromptZh);
      fd.append("feedback",fb);
      if(pickedFile) fd.append("image",pickedFile);
      const r=await fetch("/api/helper_refine",{method:"POST",body:fd});
      if(r.status===409||r.status===400||r.status===502){ const j=await r.json(); alert(j.msg); return; }
      show(await r.json());
    }else{
      // 本地模式无对话式 LLM：把意见并进想法后按本地规则重拼
      const intent=[$("intent").value.trim(),"（修改意见）"+fb].filter(Boolean).join("\n");
      const r=await fetch("/api/helper_build",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({intent,image_desc:imageDesc,presets:selectedPresets()})});
      show(await r.json());
    }
    $("refineText").value="";
  }catch(e){ alert("改稿失败："+e.message); }
  finally{ if(btn){ btn.disabled=false; btn.textContent="↻ 按我的意见改一版"; } }
}

function zoom(src){ $("lightboxImg").src=src; $("lightbox").style.display="flex"; }
function esc(t){ const d=document.createElement("div"); d.textContent=t||""; return d.innerHTML; }

// ---- 本地识图：状态 + 一键安装（下载 Ollama + 拉视觉模型，需你同意）----
let _visionPoll=null;
async function refreshVisionStatus(){
  const box=$("visionSetup");
  let s;
  try{ s=await (await fetch("/api/vision_status")).json(); }catch(e){ box.innerHTML=""; return; }
  const setup=s.setup||{};
  if(setup.active){ renderVisionProgress(setup); startVisionPoll(); return; }
  if(_visionPoll){ clearInterval(_visionPoll); _visionPoll=null; }   // 安装结束，停轮询
  // 新前端 + 旧后端（网页刷新了但 Python 服务没重启）：vision_status 不含 available
  // 字段 → 切换/正确识别都用不了、还老让你下载。明确指出"要重启服务"，别再瞎试。
  if(s.ready && !("available" in s)){
    box.innerHTML=`<div style="background:var(--field);border:1px solid #a34242;border-radius:4px;padding:10px">
        <div style="color:#d98a41;font-weight:600">⚠ 后台还是旧版本——网页更新了，但 Python 服务没重启</div>
        <div class="muted" style="margin-top:6px;line-height:1.7">本地模型「切换」要重启服务才生效：<br>
          ① 双击「停止服务.bat」（或关掉那个后台窗口）→ ② 双击「双击启动.bat」→ ③ 回来刷新本页。<br>
          <b>只刷新浏览器不够</b>——网页文件是即时的，但后台程序要重启才换成新的。</div>
      </div>`;
    return;
  }
  if(s.ready){ renderVisionReady(s, box); return; }
  const opts=Object.entries(s.choices||{}).map(([m,desc])=>
    `<option value="${m}" ${m===s.default_model?"selected":""}>${esc(m)} — ${esc(desc)}</option>`).join("");
  const hint=s.installed ? "检测到 Ollama，但还没有识图模型。"
                         : "还没装本地识图。可一键下载并安装 Ollama + 识图模型（需你同意）。";
  const failed=setup.stage==="error"?`<div style="color:#a34242;margin-top:6px">上次失败：${esc(setup.error||"")}</div>`:"";
  box.innerHTML=`<div style="background:#fff;border:1px solid var(--sand);border-radius:4px;padding:10px">
      <div class="muted" style="margin-bottom:6px">${hint}</div>
      <select id="visionModel" style="padding:6px;border:1px solid var(--sand);border-radius:3px">${opts}</select>
      <button class="go" style="width:auto;padding:8px 14px;margin-left:6px" onclick="startVisionSetup()">一键准备本地识图</button>
      ${failed}
    </div>`;
}
// 归一化模型名（与后端 _norm_model 一致：小写 + 去 - 和 .），用于判断某选择项是否已装
function normId(s){ return String(s||"").toLowerCase().replace(/[-.:]/g,""); }

// 本地识图就绪：显示「用哪个模型」的切换下拉（多个已装时）+「再装一个」入口。
// 这修好用户报的「只能用一个、切换不了、另一个用不上」——就绪后不再是死状态。
function renderVisionReady(s, box){
  const avail=s.available||[];
  // 重启后端会把选择清空；若本地存过且该模型已装，自动重新应用一次（持久化，重启不回退）
  const saved=localStorage.getItem("arch:vision_model")||"";
  if(saved && !s.selected_model && avail.includes(saved)){
    fetch("/api/set_vision_model",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({model:saved})}).then(()=>refreshVisionStatus());
    return;
  }
  const cur=s.model;   // 当前实际生效的模型
  const switcher = avail.length>1
    ? `<label class="muted" style="margin-left:8px">用哪个：</label>
       <select id="visionSwitch" onchange="switchVisionModel(this.value)"
         style="padding:5px;border:1px solid var(--sand);border-radius:3px;background:var(--field);color:var(--ink)">
         ${avail.map(m=>`<option value="${esc(m)}" ${m===cur?"selected":""}>${esc(m)}</option>`).join("")}
       </select>`
    : `<span class="muted" style="margin-left:6px">（${esc(cur)}）</span>`;
  // 选择项里还没装的 → 可以再下载一个，实现「两个都装、随时切」
  const missing=Object.entries(s.choices||{}).filter(([k])=>
    !avail.some(m=>{ const n=normId(m), h=normId(k); return n.includes(h)||h.includes(n); }));
  const dl = missing.length ? `<div class="muted" style="margin-top:8px">想再装一个随时切换：
      <select id="visionModel" style="padding:5px;border:1px solid var(--sand);border-radius:3px;background:var(--field);color:var(--ink)">
        ${missing.map(([k,d])=>`<option value="${esc(k)}">${esc(k)} — ${esc(d)}</option>`).join("")}
      </select>
      <button class="go" style="width:auto;padding:6px 12px;margin-left:6px" onclick="startVisionSetup()">下载</button>
    </div>` : "";
  box.innerHTML=`<div style="background:var(--field);border:1px solid var(--sand);border-radius:4px;padding:10px">
      <span style="color:#7fbf7f">✓ 本地识图就绪</span>${switcher}${dl}
    </div>`;
}

// 切换当前用的本地识图模型（用户在下拉里选）——存 localStorage 重启不回退
async function switchVisionModel(name){
  try{ localStorage.setItem("arch:vision_model",name); }catch(e){}
  try{
    await fetch("/api/set_vision_model",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({model:name})});
    $("descBox").textContent="已切换本地识图模型："+name+"（下次识图生效）";
    // 已选过图就用新模型立刻重新「看图理解」一次，让切换「看得见」
    if(pickedFile) understand();
  }catch(e){ alert("切换失败："+e.message); }
}

async function startVisionSetup(){
  const model=$("visionModel")?$("visionModel").value:"";
  if(!confirm(`将下载并安装 Ollama（约几百 MB）+ 识图模型 ${model}，全部在本机、离线可复用。\n下载较大、请保持联网；期间可继续用 ChatGPT 引擎。\n\n现在开始吗？`)) return;
  const j=await (await fetch("/api/vision_setup",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({model})})).json();
  if(!j.ok){ alert(j.msg||"启动失败"); return; }
  startVisionPoll(); refreshVisionStatus();
}
function startVisionPoll(){ if(!_visionPoll) _visionPoll=setInterval(refreshVisionStatus,2500); }
function renderVisionProgress(setup){
  const stageName={starting:"准备中",installing_ollama:"下载并安装 Ollama 中",
                   pulling_model:"下载识图模型中",done:"完成",error:"出错"};
  const logHtml=(setup.log||[]).slice(-8).map(esc).join("<br>");
  $("visionSetup").innerHTML=`<div style="background:#fff;border:1px solid var(--sand);border-radius:4px;padding:10px">
      <div style="color:var(--wine);font-weight:600">⏳ ${stageName[setup.stage]||setup.stage}…（可最小化，装好会自动就绪）</div>
      <div class="muted" style="font-family:monospace;font-size:11px;margin-top:6px;max-height:120px;overflow:auto">${logHtml}</div>
    </div>`;
}

setEngine("chat");
receiveHandoff();
