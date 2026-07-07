const $ = id => document.getElementById(id);
let engine = "chat", pickedFile = null, imageDesc = "";
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
    : "将在你的浏览器本地识图，不需要账号或 VPN。";
  if(e==="local" && pickedFile) runLocalVision(pickedFile);   // 切到本地即识图
}

function onPick(f){
  if(!f) return; pickedFile=f; imageDesc="";
  $("dropHint").textContent="已选择图片（可点击重选）";
  $("dropPrev").innerHTML=`<img src="${URL.createObjectURL(f)}">`;
  $("descBox").textContent="";
  if(engine==="local") runLocalVision(f);
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
}
function copyEn(){ navigator.clipboard.writeText($("en").textContent).then(()=>alert("已复制英文提示词")); }

// runLocalVision 由 Task 12 填充；先占位，本地模式暂用空描述也能拼装
async function runLocalVision(file){ /* Task 12 覆盖 */ }
setEngine("chat");
