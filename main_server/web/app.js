const $ = (s) => document.querySelector(s);
const suggestedReplies={visit_intent:"정형외과에 가야 하는데 차 좀 불러줘.",destination_category:"정형외과에 가려고 해.",reservation_consent:"응, 차 불러줘.",medical_department:"무릎이 아파서 정형외과에 가려고 해.",place_resolution_method:"가까운 곳으로 해줘.",exact_destination:"남현서울정형외과로 해줘.",date:"오늘",time:"오전 열 시",pickup_location:"집 앞에서 탈게"};
function inferRequestedSlot(text=""){
  if(text.includes("날짜"))return"date";if(text.includes("시간"))return"time";if(text.includes("출발하실 위치")||text.includes("승차 위치"))return"pickup_location";
  if(text.includes("정확한 장소명")||text.includes("주소"))return"exact_destination";if(text.includes("자주 가시는")||text.includes("가까운"))return"place_resolution_method";
  if(text.includes("어디가 불편"))return"medical_department";if(text.includes("어디에 다녀오실"))return"destination_category";if(text.includes("예약을 도와드릴까요"))return"reservation_consent";if(text.includes("어디 다녀오실 계획"))return"visit_intent";return"";
}
const names = {elder_demo_01:["김","김복순"],elder_demo_02:["박","박영수"],elder_demo_03:["이","이말순"]};
let sessionId = "", busy = false, online = false, elapsed = 0, timer;
let recognition = null, listening = false;
let audioContext = null, ringTimer = null, ringing = false;
let captionTimer = null;
let speechGeneration = 0;
let lastTrackingUrl = "";
let lastReservationReply = "";
let lastDrtAction = "";
let notificationTimer = null;
let progressDelay = null;
let progressTimers = [];
let pipelineState = {};
function cancelProgressAnimation(){
  progressTimers.forEach(clearTimeout);progressTimers=[];pipelineState={};
  document.querySelectorAll(".backend-flow li").forEach(el=>{for(const state of ["active","done","error","skipped"]){if(el.classList.contains(state))pipelineState[el.dataset.key]=state}});
}
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

async function post(path, body) {
  const response = await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  let data=null;try{data=await response.json()}catch(_){}
  if(!response.ok){const detail=typeof data?.detail==="string"?data.detail:`요청 실패 (${response.status})`;throw new Error(detail)}
  return data;
}
async function checkServer() {
  try { const r=await fetch("/",{headers:{Accept:"application/json"}}); const d=await r.json(); online=r.ok&&d.status==="ok"; } catch (_) { online=false; }
  $("#serverLabel").textContent=online?"통합 서버 연결됨":"서버 연결 안 됨";
  $(".connection").classList.toggle("online",online);
  return online;
}
function showToast(text){const el=$("#toast");el.textContent=text;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2200)}
function ringPulse(){
  if(!audioContext||audioContext.state!=="running"||!ringing)return;
  const now=audioContext.currentTime,gain=audioContext.createGain();gain.connect(audioContext.destination);gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.075,now+.025);gain.gain.setValueAtTime(.075,now+.42);gain.gain.exponentialRampToValueAtTime(.0001,now+.58);
  [440,554].forEach(f=>{const osc=audioContext.createOscillator();osc.type="sine";osc.frequency.value=f;osc.connect(gain);osc.start(now);osc.stop(now+.6)});
}
async function startRingtone(){
  if(ringing)return;ringing=true;
  try{audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();await audioContext.resume();if(audioContext.state!=="running")throw new Error();ringPulse();ringTimer=setInterval(ringPulse,1800);$("#ringHelp").classList.add("hidden")}
  catch(_){$("#ringHelp").classList.remove("hidden")}
}
function stopRingtone(){ringing=false;clearInterval(ringTimer);ringTimer=null}
function prepareRobotImage(){
  const source=$("#robotSource");
  const render=()=>{
    const size=420,off=document.createElement("canvas");off.width=size;off.height=size;
    const ctx=off.getContext("2d",{willReadFrequently:true});ctx.drawImage(source,0,0,size,size);
    const image=ctx.getImageData(0,0,size,size),data=image.data;
    for(let i=0;i<data.length;i+=4){const r=data[i],g=data[i+1],b=data[i+2];if(r>180&&b>150&&g<120){const strength=Math.min(1,((r+b)/2-g-70)/100);data[i+3]=Math.round(255*(1-strength));if(data[i+3]>0){data[i]=Math.min(r,245);data[i+2]=Math.min(b,245)}}}
    ctx.putImageData(image,0,0);
    document.querySelectorAll(".robot-canvas").forEach(canvas=>{const c=canvas.getContext("2d");c.clearRect(0,0,canvas.width,canvas.height);c.drawImage(off,0,0,canvas.width,canvas.height)});
  };
  if(source.complete)render();else source.onload=render;
}
function setupVoice(){
  if(!SpeechRecognition){$("#micButton").classList.add("hidden");return}
  recognition=new SpeechRecognition();recognition.lang="ko-KR";recognition.interimResults=true;recognition.continuous=false;
  recognition.onstart=()=>{listening=true;setActiveSpeaker("user");showCurrentSpeech("user","듣고 있어요…");$("#micButton").classList.add("listening");$("#voiceStatus").classList.remove("hidden")};
  recognition.onresult=e=>{let finalText="",interim="";for(let i=e.resultIndex;i<e.results.length;i++){const t=e.results[i][0].transcript;if(e.results[i].isFinal)finalText+=t;else interim+=t}const heard=finalText||interim;$("#utteranceInput").value=heard;if(heard)showCurrentSpeech("user",heard);if(finalText){stopListening();setTimeout(()=>send(finalText),100)}};
  recognition.onerror=e=>{stopListening();if(e.error==="not-allowed")showToast("마이크 사용 권한이 필요합니다");else if(e.error!=="no-speech")showToast("음성을 인식하지 못했습니다")};
  recognition.onend=()=>stopListening();
}
function startListening(){
  if(!recognition||listening||busy||!sessionId)return;
  window.speechSynthesis?.cancel();try{recognition.start()}catch(_){}
}
function stopListening(){listening=false;$("#micButton").classList.remove("listening");$("#voiceStatus").classList.add("hidden");try{recognition?.stop()}catch(_){}}
function speak(text,listenAfter=true,after=null){
  const generation=++speechGeneration;
  if(!("speechSynthesis" in window)){setTimeout(()=>{if(generation!==speechGeneration)return;if(after)after();else if(listenAfter)startListening()},500);return}
  setActiveSpeaker("assistant","다솜이가 말하고 있어요");$("#callScene").classList.add("speaking");
  window.speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.lang="ko-KR";utterance.rate=.92;utterance.pitch=1;
  const voices=window.speechSynthesis.getVoices();utterance.voice=voices.find(v=>v.lang.toLowerCase().startsWith("ko"))||null;
  const done=()=>{if(generation!==speechGeneration)return;$("#callScene").classList.remove("speaking");if(after)after();else if(listenAfter)setTimeout(()=>{if(generation===speechGeneration)startListening()},220)};utterance.onend=done;utterance.onerror=done;window.speechSynthesis.speak(utterance);
}
function setActiveSpeaker(role,status){
  if(!$("#callScene"))return;const user=role==="user";
  $("#dasomPerson").classList.toggle("active",!user);$("#elderPerson").classList.toggle("active",user);
  $("#dasomLine").classList.toggle("active",!user);$("#elderLine").classList.toggle("active",user);
}
function showCurrentSpeech(role,text,animate=false){
  clearInterval(captionTimer);const user=role==="user",shown=user?$("#elderLine"):$("#dasomLine"),hidden=user?$("#dasomLine"):$("#elderLine"),target=user?$("#elderSpeech"):$("#dasomSpeech");
  hidden.classList.add("turn-hidden");shown.classList.remove("turn-hidden");target.textContent=animate?"":text;
  if(animate){let i=0;captionTimer=setInterval(()=>{i++;target.textContent=text.slice(0,i);if(i>=text.length)clearInterval(captionTimer)},32)}
}
function event(text){const el=document.createElement("div");el.className="system-event";el.textContent=text;$("#conversation").append(el)}
function message(role,text,typing=false){
  const el=document.createElement("div");el.className=`message ${role}`;
  const initial=role==="user"?names[$("#userSelect").value][0]:"다";
  el.innerHTML=`<div class="avatar">${initial}</div><div class="bubble"><small>${role==="user"?"어르신":"다솜이"}</small><p></p></div>`;
  if(typing){el.querySelector("p").innerHTML="<i></i><i></i><i></i>";el.querySelector("p").className="typing"}
  else{el.querySelector("p").textContent=text;const user=role==="user";showCurrentSpeech(role,text,!user);setActiveSpeaker(role)}
  $("#conversation").append(el);$("#conversation").scrollTop=$("#conversation").scrollHeight;return el;
}
function showTestPrompt(reply=null){
  const root=$("#testPrompt");root.innerHTML="";
  if(reply?.call_ended||reply?.state?.reserved)return;
  const slot=reply?.state?.target_slot||reply?.state?.missing_slots?.[0]||inferRequestedSlot(reply?.reply);
  const text=!reply?"남현서울정형외과에 가야 하는데 차 좀 불러줘.":reply.drt_action==="awaiting_confirmation"?"응, 이 경로로 예약해줘.":slot?suggestedReplies[slot]:"";
  if(!text)return;
  const button=document.createElement("button");button.type="button";button.textContent=text;button.onclick=()=>send(text);root.append(button);
}
function showRoute(){$("#routeEmpty").classList.add("hidden");$("#routeContent").classList.remove("hidden")}
function step(key,state="done"){
  if(pipelineState[key]===state)return;
  pipelineState[key]=state;
  showRoute();const apply=()=>{const el=$(`.backend-flow li[data-key="${key}"]`);if(!el)return;el.classList.remove("active","done","error","skipped");el.classList.add(state);el.querySelector(":scope>b").textContent=state==="done"?"완료":state==="error"?"실패":state==="skipped"?"해당 없음":"진행 중"};
  if(progressDelay===null)apply();else{progressTimers.push(setTimeout(apply,progressDelay));progressDelay+=280}
}
function resetPipelineSteps(){
  pipelineState={};
  document.querySelectorAll(".backend-flow li").forEach(el=>{el.classList.remove("active","done","error","skipped");el.querySelector(":scope>b").textContent="대기"});
}
const detailLabels={
  unknown:"확인 전",need_detection:"이동 필요 확인",reservation_confirm:"예약 의사 확인",reservation_info_collection:"예약 정보 수집",not_needed:"이동 요청 없음",emergency:"응급 대응",
  medical_general:"병원",medical_dental:"치과",medical_orthopedics:"정형외과",medical_dermatology:"피부과",medical_internal:"내과",medical_neurology:"신경과",medical_ophthalmology:"안과",medical_ent:"이비인후과",medical_rehabilitation:"재활의학과",shopping_market:"시장",
  not_asked:"미확인",not_confirmed:"미확정",confirmed:"동의",refused:"거절",awaiting_confirmation:"경로 확인 대기",reserved:"예약 완료",backend_error:"백엔드 오류",
  visit_intent:"외출 의사",destination_category:"목적지",reservation_consent:"차량 예약 동의",medical_department:"진료과",place_resolution_method:"장소 선택 방식",exact_destination:"정확한 장소",date:"날짜",time:"시간",pickup_location:"승차 위치"
};
function detailValue(value){if(value===true)return"있음";if(value===false||value===undefined||value===null||value==="")return"없음";return detailLabels[value]||String(value)}
async function showMessageScreen(showNotification=false,reserved=false){
  ++speechGeneration;stopListening();clearInterval(timer);const ended=sessionId;sessionId="";
  if(ended){try{await post("/call/end",{session_id:ended,text:reserved?"예약 완료":"통화 종료"})}catch(_){}}
  $(".chat-shell").classList.add("message-mode");$("#callScene").classList.add("hidden");$("#messageScreen").classList.remove("hidden");$("#elapsed").textContent="종료";
  $("#callEndedText").textContent=reserved?"차량 예약 후 통화가 종료되었습니다":"다솜이와의 통화가 종료되었습니다";
  $("#lockTime").textContent=new Date().toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",hour12:false});
  $("#notificationText").textContent=lastReservationReply||"차량 예약 결과를 확인했습니다.";
  $("#notificationLink").classList.toggle("hidden",!lastTrackingUrl);$("#notificationLink").onclick=openTrackingInPhone;
  $("#messageNotification").classList.add("hidden");
  if(showNotification)notificationTimer=setTimeout(()=>$("#messageNotification").classList.remove("hidden"),700);
}
function openTrackingInPhone(){
  if(!lastTrackingUrl){showToast("백엔드에서 조회 링크를 제공하지 않았습니다");return}
  $("#messageScreen").classList.add("hidden");$("#phoneTracking").classList.remove("hidden");const frame=$("#trackingFrame");$("#trackingLoading").classList.remove("hidden");frame.classList.add("hidden");frame.onload=()=>{$("#trackingLoading").classList.add("hidden");frame.classList.remove("hidden")};frame.src=lastTrackingUrl;
}
function closeTracking(){$("#phoneTracking").classList.add("hidden");$("#messageScreen").classList.remove("hidden")}
function reloadPhoneTracking(){const frame=$("#trackingFrame");if(frame.src)frame.src=frame.src}
function resetTracking(){$("#phoneTracking").classList.add("hidden");$("#trackingFrame").onload=null;$("#trackingFrame").src="";$("#trackingLoading").classList.remove("hidden")
}
function beginBackendWork(){
  cancelProgressAnimation();progressDelay=null;
  showRoute();
  if(lastDrtAction==="awaiting_confirmation"){
    step("reserve","active");
    $("#routeStatus").textContent="차량 예약 요청 중";
  }else{
    step("analyze","active");
    $("#routeStatus").textContent="요청 분석 중";
  }
}
function renderLiveProgress(reply){
  const state=reply.state||{},action=reply.drt_action||"",stage=state.dialogue_stage||"unknown";
  const wasAwaiting=lastDrtAction==="awaiting_confirmation";
  lastDrtAction=action;
  step("analyze","done");
  if(action==="emergency"||stage==="emergency"){
    step("collect","skipped");step("plan","skipped");step("reserve","skipped");step("notify","skipped");$("#routeStatus").textContent="응급 대응 우선 · DRT 미진행";return;
  }
  if(stage==="not_needed"){
    step("collect","skipped");step("plan","skipped");step("reserve","skipped");step("notify","skipped");$("#routeStatus").textContent="이동 요청 없음 · DRT 미진행";return;
  }
  if(stage==="unknown"||stage==="need_detection"){
    step("collect","active");$("#routeStatus").textContent="이동 필요 확인 중";return;
  }
  if(action==="awaiting_confirmation"){
    step("collect","done");step("plan","done");step("reserve","active");$("#routeStatus").textContent="경로 계산 완료 · 최종 동의 대기";
  }else if(action==="reserved"||state.reserved){
    step("collect","done");step("plan","done");step("reserve","done");step("notify",reply.tracking_url||reply.sms_sent?.length?"done":"skipped");$("#routeStatus").textContent="차량 예약 완료";
    lastTrackingUrl=reply.tracking_url||"";event("차량 예약 완료");showToast("차량 예약이 완료되었습니다");
  }else if(action==="backend_error"){
    if(wasAwaiting){step("reserve","error");$("#routeStatus").textContent="차량 예약 실패"}
    else{step("plan","error");$("#routeStatus").textContent="경로 계산 실패"}
  }else{
    step("collect","active");$("#routeStatus").textContent=stage==="reservation_confirm"?"차량 예약 의사 확인 중":"예약 정보 수집 중";
  }
}
function inferLiveProgress(reply){
  showRoute();cancelProgressAnimation();progressDelay=180;
  renderLiveProgress(reply);progressDelay=null;
}
async function start(){
  if(busy)return;stopRingtone();busy=true;$("#startButton").disabled=true;
  try{
    let greeting="안녕하세요, 다솜이에요. 오늘은 어떻게 지내셨어요?";
    if(!await checkServer())throw new Error("실제 API 서버에 연결할 수 없습니다. 서버 상태를 확인해 주세요.");
    const data=await post("/call/start",{user_id:$("#userSelect").value});sessionId=data.session_id;greeting=data.reply;showToast("실제 API로 연결했습니다");
    $("#userSelect").disabled=true;
    elapsed=0;$(".chat-shell").classList.add("in-call");$("#elderName").textContent=names[$("#userSelect").value][1]+" 어르신";$("#elderSpeechName").textContent=names[$("#userSelect").value][1]+" 어르신";$("#startScreen").classList.add("hidden");$("#callScene").classList.remove("hidden");$("#resetButton").classList.remove("hidden");
    event("통화가 연결되었습니다");message("assistant",greeting);showTestPrompt();speak(greeting);
    clearInterval(timer);timer=setInterval(()=>{elapsed++;$("#elapsed").textContent=`${String(Math.floor(elapsed/60)).padStart(2,"0")}:${String(elapsed%60).padStart(2,"0")}`},1000);
  }catch(e){showToast(e.message);if(!sessionId)setTimeout(startRingtone,350)}finally{busy=false;$("#startButton").disabled=false}
}
async function send(text){
  text=text.trim();if(!text||busy||!sessionId)return;++speechGeneration;stopListening();window.speechSynthesis?.cancel();$("#callScene").classList.remove("speaking");busy=true;$("#utteranceInput").value="";message("user",text);beginBackendWork();const typing=message("assistant","",true);
  try{
    const reply=await post("/call/utterance",{session_id:sessionId,text});
    typing.remove();message("assistant",reply.reply);
    inferLiveProgress(reply);
    const reservationDone=Boolean(reply.drt_action==="reserved"||reply.state?.reserved||reply.tracking_url||reply.sms_sent?.length);
    const terminal=Boolean(reply.call_ended||reservationDone),showReservationNotice=Boolean(reservationDone&&(reply.sms_sent?.length||reply.tracking_url));
    if(reservationDone)lastReservationReply=reply.reply;
    showTestPrompt(reply);speak(reply.reply,!terminal,terminal?()=>showMessageScreen(showReservationNotice,reservationDone):null);
  }catch(e){typing.remove();event(`오류 · ${e.message}`);showToast(e.message)}finally{busy=false}
}
async function reset(){
  ++speechGeneration;stopRingtone();stopListening();clearInterval(captionTimer);clearTimeout(notificationTimer);window.speechSynthesis?.cancel();
  if(sessionId){try{await post("/call/end",{session_id:sessionId,text:"종료"})}catch(_){}}
  sessionId="";$("#testPrompt").innerHTML="";clearInterval(timer);$(".chat-shell").classList.remove("in-call","message-mode");$("#elapsed").textContent="00:00";$("#conversation").innerHTML="";$("#conversation").classList.add("hidden");$("#composer").classList.add("hidden");$("#startScreen").classList.remove("hidden");$("#resetButton").classList.add("hidden");
  $("#userSelect").disabled=false;
  $("#callScene").classList.add("hidden");
  $("#messageScreen").classList.add("hidden");lastTrackingUrl="";lastReservationReply="";lastDrtAction="";cancelProgressAnimation();progressDelay=null;resetTracking();
  $("#routeContent").classList.add("hidden");$("#routeEmpty").classList.remove("hidden");
  $("#messageNotification").classList.add("hidden");
  resetPipelineSteps();$("#routeStatus").textContent="요청 확인 중";
  setTimeout(startRingtone,350);
}
function declineCall(){stopRingtone();$(".incoming-label").textContent="부재중 전화";$("#ringHelp").textContent="다시 전화 걸기";$("#ringHelp").classList.remove("hidden");showToast("전화를 받지 않았습니다")}
$("#startButton").onclick=start;$("#declineButton").onclick=declineCall;$("#ringHelp").onclick=()=>{$(".incoming-label").textContent="수신 전화";$("#ringHelp").textContent="벨소리 켜기";stopRingtone();startRingtone()};$("#resetButton").onclick=reset;$("#newCallButton").onclick=reset;$("#endCallButton").onclick=reset;$("#trackingBack").onclick=closeTracking;$("#trackingReload").onclick=reloadPhoneTracking;$("#micButton").onclick=()=>listening?stopListening():startListening();$("#callScene").onclick=e=>{if(!e.target.closest("#endCallButton")&&!listening&&!busy)startListening()};$("#utteranceForm").onsubmit=e=>{e.preventDefault();send($("#utteranceInput").value)};prepareRobotImage();setupVoice();checkServer();setTimeout(startRingtone,250);document.addEventListener("pointerdown",()=>{if(ringing&&audioContext?.state!=="running"){stopRingtone();startRingtone()}},{once:true});
