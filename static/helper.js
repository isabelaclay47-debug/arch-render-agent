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
    : "将用本机 Ollama 视觉模型离线识图，免账号免 VPN（首次需装 Ollama 并 pull 一个视觉模型，如 qwen2.5-vl）。";
  if(e==="local" && pickedFile) runLocalVision(pickedFile);   // 切到本地即识图
}

function onPick(f){
  if(!f) return; pickedFile=f; imageDesc="";
  $("dropHint").textContent="已选择图片（可点击重选，点图放大）";
  $("dropPrev").innerHTML=`<img src="${URL.createObjectURL(f)}" style="cursor:zoom-in"
        onclick="event.stopPropagation();zoom(this.src)">`;
  $("descBox").textContent="";
  $("toRenderBtn").style.display="block";        // 有图了才能发给渲染器
  if(engine==="local") runLocalVision(f);
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
  return [...document.querySelectorAll("#presets input:checked")].map(el=>PRESETS[+el.value][1]);
}

async function generate(){
  const intent=$("intent").value.trim();
  const presets=selectedPresets();
  if(engine==="local"){
    const r=await fetch("/api/helper_build",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({intent,image_desc:imageDesc,presets})});
    show(await r.json());
  }else{
    const fd=new FormData();
    fd.append("draft_prompt",[intent,...presets].filter(Boolean).join("\n"));
    if(pickedFile) fd.append("image",pickedFile);
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

// 本地识图：交给后端的本机 Ollama 视觉模型（真·本地部署、离线、零 API key）。
// 没装 Ollama / 没视觉模型时后端返回 ok=false + 安装指引，这里如实展示、优雅降级。
async function runLocalVision(file){
  $("descBox").textContent="本地识图中（首次可能较慢）…";
  try{
    const fd=new FormData(); fd.append("image",file);
    const j=await (await fetch("/api/helper_vision",{method:"POST",body:fd})).json();
    if(j.ok){
      imageDesc=(j.desc||"").trim();
      $("descBox").textContent="本地识图（"+j.model+"）：" + (imageDesc||"（未识别，可手动补充画面描述）");
    }else{
      imageDesc="";
      $("descBox").textContent=j.msg||"本地识图暂不可用，可直接在想法里描述画面。";
    }
  }catch(e){
    imageDesc="";
    $("descBox").textContent="本地识图失败（"+e.message+"）。可直接在想法里描述画面后生成。";
  }
}

function zoom(src){ $("lightboxImg").src=src; $("lightbox").style.display="flex"; }
setEngine("chat");
receiveHandoff();
