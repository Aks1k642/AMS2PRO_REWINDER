'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const densityTable = {PLA:1.24,PETG:1.27,ABS:1.04,ASA:1.07,TPU:1.21,PA:1.14,PC:1.20};
  const number = id => Number($(id).value);
  const format = (n, digits=1) => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(n);
  let plans = [];
  let lastState = null;
  let lastCheck = null;
  let lastCheckAt = 0;
  let activePlanId = null;
  let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
  try { plans = JSON.parse(localStorage.getItem('ams-rewinder-plans') || '[]'); if(!Array.isArray(plans)) plans=[]; } catch { plans=[]; }
  let toastTimeout;
  function toast(message, error=false){ const box=$('toast');box.textContent=message;box.classList.toggle('error',error);box.classList.add('show');clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>box.classList.remove('show'),5500); }
  function estimate(){
    const density=number('density'),dia=number('diameter'),grams=number('grams'),before=number('starting'),capacity=number('capacity');
    const valid=[density,dia,grams,before,capacity].every(Number.isFinite)&&density>0&&dia>0&&grams>0&&before>=0&&capacity>0;
    const weightPerMeter=valid?density*Math.PI*(dia*dia/4):0;
    const metres=valid?grams/weightPerMeter:0;
    const fill=valid?100*(before+grams)/capacity:0;
    $('metres').textContent=valid?format(metres):'—';
    $('gpm').textContent=valid?format(weightPerMeter,2)+' г':'—';
    $('totalWeight').textContent=valid?format(before+grams,0)+' г':'—';
    $('fillLabel').textContent=valid?format(fill,0)+'%':'—';
    $('fillBar').style.width=Math.min(100,Math.max(0,fill))+'%';
    $('fillBar').style.background=fill>100?'#eb6878':'linear-gradient(90deg,#7e3655,#f18ab1)';
    $('overfill').textContent= !valid?'Проверь числовые значения.':fill>100?'ВНИМАНИЕ: переполнение на '+format(before+grams-capacity,0)+' г!':'Оценка без датчика метража и фактического веса.';
    $('overfill').classList.toggle('error',!valid||fill>100);
    $('savePlan').disabled=!valid;
    return valid?{material:$('material').value,density,dia,grams,before,capacity,metres,fill}:null;
  }
  function savePlans(){
    try{localStorage.setItem('ams-rewinder-plans',JSON.stringify(plans));}
    catch{toast('Не удалось сохранить план в браузере',true);}
    drawPlans();
  }
  function refreshActivePlan(){
    const plan=plans.find(x=>x.id===activePlanId);
    const root=$('activePlan');
    if(!plan){root.textContent='Выбери «В работу» у сохранённого плана.';}
    else{
      const progress=Math.max(0,Number(plan.actualGrams)||0);
      root.textContent=plan.material+' · цель '+format(plan.grams,0)+' г ('+format(plan.metres)+' м). Факт по весам: '+format(progress,0)+' г. '+format(progress/plan.grams*100,0)+'% цели. Статус: '+(plan.state||'planned')+'. Это ручной учёт, не телеметрия AMS.';
      $('actualGrams').value=progress;
      $('planNote').value=plan.note||'';
    }
    ['recordPlan','completePlan','cancelPlan'].forEach(id=>$(id).disabled=!plan);
  }
  function drawPlans(){
    const root=$('plans');root.replaceChildren();
    if(!plans.length){const p=document.createElement('p');p.className='muted-small';p.textContent='Планов пока нет.';root.append(p);}
    plans.forEach((x,i)=>{
      if(!x.id)x.id=String(Date.now())+'-'+String(i);
      const row=document.createElement('div');row.className='plan';
      const content=document.createElement('div');const strong=document.createElement('strong');
      strong.textContent=`${format(x.grams,0)} г · ${x.material} · ${format(x.metres)} м`;
      const small=document.createElement('small');
      small.textContent=`${x.date} · ${x.state||'planned'} · факт ${format(Number(x.actualGrams)||0,0)} г · план без автоматической перемотки`;
      content.append(strong,small);
      const start=document.createElement('button');start.type='button';start.textContent='В работу';
      start.addEventListener('click',()=>{
        const prior=plans.find(p=>p.id===activePlanId);
        if(prior&&prior.state==='in_progress')prior.state='paused';
        activePlanId=x.id;x.state='in_progress';savePlans();refreshActivePlan();
        document.getElementById('activePlan').scrollIntoView({behavior:'smooth',block:'center'});
      });
      const remove=document.createElement('button');remove.type='button';remove.textContent='Удалить';
      remove.addEventListener('click',()=>{if(x.id===activePlanId)activePlanId=null;plans.splice(i,1);savePlans();});
      row.append(content,start,remove);root.append(row);
    });
    refreshActivePlan();
  }
  function writePlan(complete=false){
    const plan=plans.find(x=>x.id===activePlanId);
    if(!plan){toast('Сначала выбери план «В работу».',true);return;}
    const actual=Number($('actualGrams').value);
    if(!Number.isFinite(actual)||actual<0||actual>10000){toast('Введите реальное значение массы от 0 до 10000 г.',true);return;}
    plan.actualGrams=actual;plan.note=$('planNote').value.slice(0,100);
    plan.state=complete?'completed':'in_progress';
    plan.updated=new Date().toLocaleString('ru-RU');
    if(complete)activePlanId=null;
    savePlans();toast(complete?'План завершён; фактическая масса записана.':'Фактическая масса записана (вручную).');
  }
  $('recordPlan').addEventListener('click',()=>writePlan(false));
  $('completePlan').addEventListener('click',()=>writePlan(true));
  $('cancelPlan').addEventListener('click',()=>{
    const plan=plans.find(x=>x.id===activePlanId);
    if(plan)plan.state='paused';
    activePlanId=null;savePlans();toast('Учёт плана приостановлен. Управление мотором не выполнялось.');
  });
  function escapeCSV(value){return '"'+String(value).replaceAll('"','""')+'"';}
  function exportCSV(){if(!plans.length){toast('Нет сохранённых планов');return;}const cols=['date','material','density','dia','grams','before','capacity','metres','fill'];const rows=[cols.join(';'),...plans.map(item=>cols.map(key=>escapeCSV(item[key])).join(';'))];const blob=new Blob(['\ufeff'+rows.join('\r\n')],{type:'text/csv;charset=utf-8;'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='ams_rewinder_plans.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('material').addEventListener('change',()=>{if(densityTable[$('material').value])$('density').value=densityTable[$('material').value];estimate();});
  ['density','diameter','grams','starting','capacity'].forEach(id=>$(id).addEventListener('input',()=>{estimate();document.querySelectorAll('.chip').forEach(btn=>btn.classList.toggle('selected',Number(btn.dataset.grams)===number('grams')))}));
  document.querySelectorAll('.chip').forEach(btn=>btn.addEventListener('click',()=>{$('grams').value=btn.dataset.grams;document.querySelectorAll('.chip').forEach(b=>b.classList.toggle('selected',b===btn));estimate();}));
  $('savePlan').addEventListener('click',()=>{const v=estimate();if(!v)return;plans.unshift({...v,id:String(Date.now())+'-'+Math.random().toString(36).slice(2,8),state:'planned',actualGrams:0,note:'',date:new Date().toLocaleString('ru-RU')});plans=plans.slice(0,300);savePlans();toast('План добавлен в историю (без реального движения AMS).');});
  $('exportCsv').addEventListener('click',exportCSV);
  $('clearHistory').addEventListener('click',()=>{if(confirm('Удалить все локальные планы?')){plans=[];activePlanId=null;savePlans();}});
  async function api(route,body){if(!token)throw Error('Нет токена локального сервера. Для управления запусти START_WINDOWS.cmd и открой выданную ссылку.');const c=new AbortController();const timer=setTimeout(()=>c.abort(),11000);try{const response=await fetch('/api/'+route,{method:body?'POST':'GET',headers:{'X-Session-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:c.signal,cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'HTTP '+response.status);return data;}finally{clearTimeout(timer);}}
  async function discoverDevices(){
    const button=$('discover'), selection=$('devices');
    button.disabled=true;selection.replaceChildren();
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Поиск в локальной сети…';selection.append(placeholder);
    $('discoveryMessage').textContent='Слушаем объявления Bambu Lab на UDP 2021 (примерно 6 секунд)…';
    try {
      const result=await api('discover');
      selection.replaceChildren();
      const empty=document.createElement('option');empty.value='';empty.textContent='Выбери найденный принтер';selection.append(empty);
      for(const device of result.devices||[]){
        const option=document.createElement('option');
        option.value=device.serial;
        option.dataset.model=device.model||'';
        option.dataset.saved=device.saved_code?'yes':'no';
        option.textContent=(device.name||'Bambu Lab')+' · '+device.host+(device.model?' · '+device.model:' · модель не определена')+(device.saved_code?' · код сохранён':'');
        selection.append(option);
      }
      $('discoveryMessage').textContent=result.devices?.length
        ?'Найдено: '+result.devices.length+'. Выбери принтер. Серийный номер подставится автоматически.'
        :'Принтеры не найдены. Проверь общую сеть, UDP 2021 и закрытие Bambu Studio. Можно открыть ручной режим.';
      if(result.devices?.length===1){selection.selectedIndex=1;selection.dispatchEvent(new Event('change'));}
    } catch(error){
      selection.replaceChildren();
      const failed=document.createElement('option');failed.value='';failed.textContent='Не обнаружено';selection.append(failed);
      $('discoveryMessage').textContent='Ошибка поиска: '+error.message;
      toast('Поиск принтеров не удался: '+error.message,true);
    } finally{button.disabled=false;}
  }
  $('discover').addEventListener('click',discoverDevices);
  $('devices').addEventListener('change',()=>{
    const selected=$('devices').selectedOptions[0];
    if(selected?.dataset.model && ['H2S','P2S','X2D'].includes(selected.dataset.model))$('model').value=selected.dataset.model;
    if($('devices').value)$('manualConnection').open=false;
    $('savedCodeStatus').textContent=selected?.dataset.saved==='yes'?'Код для этого SN уже сохранён':'Для этого SN код не найден';
    $('accessCode').placeholder=selected?.dataset.saved==='yes'?'Оставь пустым для сохранённого кода':'Введи LAN Access Code';
  });
  const stateLabel=s=>({RUNNING:'Печатает',PREPARE:'Подготовка',IDLE:'Ожидание',FINISH:'Завершено',FAILED:'Ошибка',PAUSE:'Пауза',STOP:'Остановлен'})[String(s||'').toUpperCase()]||s||'—';
  function renderCheck(result){
    lastCheck=result;lastCheckAt=Date.now();
    const checks=$('unloadChecks');checks.replaceChildren();
    const all=[...(result.blockers||[]),...(result.warnings||[])];
    if(!all.length){checks.textContent='Все программные проверки выполнены. Это не гарантирует, что команда поддерживается прошивкой.';}
    else all.forEach(x=>{const row=document.createElement('div');
      const prefix=(result.blockers||[]).includes(x)?'НЕ ГОТОВО: ':'Предупреждение: ';
      row.textContent=prefix+x.message+' → '+x.action;checks.append(row);});
    validateUnload();
  }
  async function checkUnload(){
    if(!token){$('unloadReason').textContent='Для проверки нужен работающий Windows LAN-мост.';return;}
    try{
      const result=await api('check',{unit:Number($('unit').value),slot:Number($('slot').value)});
      renderCheck(result);
    }catch(e){
      lastCheck=null;$('unloadChecks').textContent='Не удалось проверить готовность: '+e.message;
      $('unload').disabled=true;
    }
  }
  function updateStatus(data){
    if(!data.connected || lastState?.printer?.serial_masked !== data.printer?.serial_masked || data.readiness?.stage==='waiting_status'){
      lastCheck=null;
    }
    lastState=data;const t=data.status||{},active=data.connected, ready=data.readiness||{};
    const stage=!active?'Не подключено':ready.stage==='waiting_status'?'Ожидание телеметрии':ready.stage==='ready'?'MQTT + AMS готовы':'Подключено · нужны действия';
    $('connectionBadge').textContent=stage;$('connectionBadge').classList.toggle('offline',!active);
    $('sideStatus').textContent=stage;$('sideDot').classList.toggle('muted',!active);
    $('gcodeState').textContent=stateLabel(t.gcode_state);$('amsStatus').textContent=t.ams_status??'—';
    $('trayNow').textContent=t.ams?.tray_now==null?'—':String(t.ams.tray_now);
    $('telemetryAge').textContent=data.telemetry_age_s==null?'—':data.telemetry_age_s+' с';
    $('lastCommand').textContent=data.last_command?(data.last_command.command+' · '+(data.last_command.result||'запрос без ответа')):'—';
    const details=$('connectionSteps');details.replaceChildren();
    if(data.connection_error){const p=document.createElement('div');p.textContent='Ошибка соединения: '+data.connection_error;details.append(p);}
    for(const x of ready.blockers||[]){const d=document.createElement('div');d.textContent='Не готово: '+x.message+' → '+x.action;details.append(d);}
    for(const x of ready.warnings||[]){const d=document.createElement('div');d.textContent='Проверить: '+x.message+' → '+x.action;details.append(d);}
    if(ready.ready&&!ready.warnings?.length)details.textContent='Сеть отвечает, AMS готов по доступной телеметрии. Для выгрузки выбери правильный слот и подтверди присутствие.';
    if(!active&&!(ready.blockers||[]).length)details.textContent='Не подключено. Найди принтер, введи код и нажми «Подключиться».';
    $('savedCodeStatus').textContent=data.printer?.saved_code?'Для подключённого SN код сохранён':(data.vault_available?'Для подключённого SN код не сохранён':'Хранение кодов доступно только на Windows');
    const events=$('events');events.replaceChildren();
    if(!data.events?.length){events.textContent='Нет событий';}else data.events.slice().reverse().forEach(e=>{const line=document.createElement('div');line.textContent=e.at+' · '+e.text;events.append(line);});
    validateUnload();
  }
  function validateUnload(){
    const pending=!lastCheck||Date.now()-lastCheckAt>12000;
    const good=!!lastCheck?.ready&&!pending&&$('noSplice').checked&&$('atPrinter').checked;
    $('unload').disabled=!good;
    if(pending)$('unloadReason').textContent='Нужна свежая проверка: нажми «Проверить готовность».';
    else if(!lastCheck.ready)$('unloadReason').textContent='Команда заблокирована. Устрани перечисленные ниже препятствия.';
    else if(!$('noSplice').checked||!$('atPrinter').checked)$('unloadReason').textContent='Подтверди отсутствие спайки и присутствие у принтера.';
    else $('unloadReason').textContent='Можно отправить ровно одну штатную команду. Результат зависит от прошивки.';
  }
  async function refresh(){
    if(!token){$('bridgeMessage').textContent='Автономный калькулятор: нужен Windows LAN-мост для управления.';return;}
    try{
      const state=await api('status');updateStatus(state);
      $('bridgeMessage').textContent=state.connected?'Сетевое соединение установлено. Проверь разрешение команд и состояние AMS выше.':'MQTT не подключён. Найди устройство, введи код и включи LAN/Developer Mode.';
      await checkUnload();
    }catch(e){$('bridgeMessage').textContent='Сервер недоступен: '+e.message;lastState=null;lastCheck=null;validateUnload();}
  }
  $('checkUnload').addEventListener('click',checkUnload);
  $('refreshTelemetry').addEventListener('click',async()=>{
    const button=$('refreshTelemetry');button.disabled=true;
    try{
      const data=await api('refresh-status',{});
      toast(data.message||'Запрос состояния отправлен.');
      await refresh();
    }catch(e){toast(e.message,true);}
    finally{button.disabled=false;}
  });
  $('connect').addEventListener('click',async()=>{const button=$('connect');button.disabled=true;lastCheck=null;validateUnload();try{const manual=$('manualConnection').open;const deviceId=$('devices').value;
    if(!manual&&!deviceId)throw Error('Сначала нажми «Найти принтеры» и выбери устройство либо открой ручной режим.');
    const cfg={model:$('model').value,access_code:$('accessCode').value,
      remember_code:$('rememberCode').checked,use_saved_code:true,
      ...(manual?{host:$('host').value,serial:$('serial').value}:{device_id:deviceId})};const result=await api('connect',cfg);$('accessCode').value='';updateStatus(result);toast('MQTT подключён. Дождись проверки AMS и разрешения команд.');await refresh();}catch(e){toast(e.message,true);}finally{button.disabled=false;}});
  $('forgetCode').addEventListener('click',async()=>{
    try{
      const serial=$('manualConnection').open?$('serial').value:$('devices').value;
      if(!serial)throw Error('Выбери принтер из поиска либо введи SN в ручном режиме.');
      if(!confirm('Удалить сохранённый LAN Access Code для выбранного серийного номера?'))return;
      await api('forget-code',{device_id:serial});
      $('savedCodeStatus').textContent='Сохранённый код удалён';
      const opt=$('devices').selectedOptions[0];if(opt)opt.dataset.saved='no';
      toast('Код доступа удалён с этого Windows-компьютера.');
    }catch(e){toast(e.message,true);}
  });
  $('disconnect').addEventListener('click',async()=>{try{const result=await api('disconnect',{});updateStatus(result);toast('Подключение закрыто.');}catch(e){toast(e.message,true)}});
  $('unload').addEventListener('click',async()=>{validateUnload();if($('unload').disabled)return;
    if(!confirm('ТЕСТ НА ОДНОЙ КАТУШКЕ БЕЗ СПАЙКИ.\n\nОтправить ровно ОДНУ штатную команду выгрузки на принтер? Не гарантируется движение или автоматическая остановка.'))return;
    $('unload').disabled=true;try{const data=await api('unload',{confirm:'Я НАХОЖУСЬ У ПРИНТЕРА',joined_spools:false,unit:Number($('unit').value),slot:Number($('slot').value),method:$('unloadMethod').value});toast(data.warning);await refresh();}catch(e){toast(e.message,true);}finally{setTimeout(validateUnload,600);}
  });
  ['unit','slot'].forEach(id=>$(id).addEventListener('change',checkUnload));
  ['noSplice','atPrinter'].forEach(id=>$(id).addEventListener('change',validateUnload));
  document.querySelectorAll('a.navlink').forEach(link=>link.addEventListener('click',e=>{e.preventDefault();document.querySelector(link.getAttribute('href'))?.scrollIntoView({behavior:'smooth'});document.querySelectorAll('a.navlink').forEach(x=>x.classList.toggle('active',x===link));}));
  estimate();drawPlans();validateUnload();refresh();if(!token){$('discover').disabled=true;$('checkUnload').disabled=true;$('refreshTelemetry').disabled=true;$('forgetCode').disabled=true;$('discoveryMessage').textContent='Автономный режим: для поиска принтеров открой приложение через Windows LAN-мост.';}else{setInterval(refresh,3000);}
})();
