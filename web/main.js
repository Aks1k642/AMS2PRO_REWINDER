'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const densityTable = {PLA:1.24,PETG:1.27,ABS:1.04,ASA:1.07,TPU:1.21,PA:1.14,PC:1.20};
  const number = id => Number($(id).value);
  const format = (n, digits=1) => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(n);
  let plans = [];
  let lastState = null;
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
  function savePlans(){try{localStorage.setItem('ams-rewinder-plans',JSON.stringify(plans))}catch{toast('Не удалось сохранить в браузере',true)}drawPlans();}
  function drawPlans(){const root=$('plans');root.replaceChildren();if(!plans.length){const p=document.createElement('p');p.className='muted-small';p.textContent='Планов пока нет.';root.append(p);return;}
    plans.forEach((x,i)=>{const row=document.createElement('div');row.className='plan';const content=document.createElement('div');const strong=document.createElement('strong');strong.textContent=`${format(x.grams,0)} г · ${x.material} · ${format(x.metres)} м`;const small=document.createElement('small');small.textContent=`${x.date} · Ø${x.dia} мм · заполнение ${format(x.fill,0)}% · план, не фактическая перемотка`;content.append(strong,small);const btn=document.createElement('button');btn.textContent='Удалить';btn.addEventListener('click',()=>{plans.splice(i,1);savePlans()});row.append(content,btn);root.append(row);});}
  function escapeCSV(value){return '"'+String(value).replaceAll('"','""')+'"';}
  function exportCSV(){if(!plans.length){toast('Нет сохранённых планов');return;}const cols=['date','material','density','dia','grams','before','capacity','metres','fill'];const rows=[cols.join(';'),...plans.map(item=>cols.map(key=>escapeCSV(item[key])).join(';'))];const blob=new Blob(['\ufeff'+rows.join('\r\n')],{type:'text/csv;charset=utf-8;'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='ams_rewinder_plans.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('material').addEventListener('change',()=>{if(densityTable[$('material').value])$('density').value=densityTable[$('material').value];estimate();});
  ['density','diameter','grams','starting','capacity'].forEach(id=>$(id).addEventListener('input',()=>{estimate();document.querySelectorAll('.chip').forEach(btn=>btn.classList.toggle('selected',Number(btn.dataset.grams)===number('grams')))}));
  document.querySelectorAll('.chip').forEach(btn=>btn.addEventListener('click',()=>{$('grams').value=btn.dataset.grams;document.querySelectorAll('.chip').forEach(b=>b.classList.toggle('selected',b===btn));estimate();}));
  $('savePlan').addEventListener('click',()=>{const v=estimate();if(!v)return;plans.unshift({...v,date:new Date().toLocaleString('ru-RU')});plans=plans.slice(0,300);savePlans();toast('План добавлен в историю (без реального движения AMS).');});
  $('exportCsv').addEventListener('click',exportCSV);
  $('clearHistory').addEventListener('click',()=>{if(confirm('Удалить все локальные планы?')){plans=[];savePlans();}});
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
        option.textContent=(device.name||'Bambu Lab')+' · '+device.host+(device.model?' · '+device.model:' · модель не определена');
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
  });
  const stateLabel=s=>({RUNNING:'Печатает',PREPARE:'Подготовка',IDLE:'Ожидание',FINISH:'Завершено',FAILED:'Ошибка',PAUSE:'Пауза',STOP:'Остановлен'})[String(s||'').toUpperCase()]||s||'—';
  function updateStatus(data){lastState=data;const t=data.status||{},active=data.connected;
    $('connectionBadge').textContent=active?'Подключено':'Не подключено';$('connectionBadge').classList.toggle('offline',!active);
    $('sideStatus').textContent=active?'MQTT подключён':'Расчёт офлайн';$('sideDot').classList.toggle('muted',!active);
    $('gcodeState').textContent=stateLabel(t.gcode_state);$('amsStatus').textContent=t.ams_status??'—';
    $('trayNow').textContent=t.ams?.tray_now==null?'—':String(t.ams.tray_now);
    $('telemetryAge').textContent=data.telemetry_age_s==null?'—':data.telemetry_age_s+' с';
    $('lastCommand').textContent=data.last_command?(data.last_command.command+' · '+(data.last_command.result||'без ответа')):'—';
    const events=$('events');events.replaceChildren();if(!data.events?.length){events.textContent='Нет событий';} else data.events.slice().reverse().forEach(e=>{const line=document.createElement('div');line.textContent=e.at+' · '+e.text;events.append(line);});
    validateUnload();
  }
  function validateUnload(){const s=lastState;const tray=Number($('unit').value)*4+Number($('slot').value);let problem='';if(!s?.connected)problem='Принтер не подключён.';else if(s.telemetry_age_s===null||s.telemetry_age_s>10)problem='Нет свежих данных от принтера.';else if(!['IDLE','FINISH'].includes(String(s.status?.gcode_state||'').toUpperCase()))problem='Принтер не в режиме ожидания.';else if(s.status?.ams_status==null||![0,3].includes((Number(s.status.ams_status)>>8)))problem='AMS занят или состояние AMS неизвестно.';else if(s.status?.ams?.tray_now==null)problem='Нет данных об активной катушке AMS.';else if(Number(s.status.ams.tray_now)!==tray)problem='Выбранный слот не является активным в тракте.';else if(!$('noSplice').checked||!$('atPrinter').checked)problem='Подтверди безопасные условия теста.';else problem='Один тестовый запрос разрешён. Никакой непрерывной перемотки.';$('unloadReason').textContent=problem;$('unload').disabled=problem!=='Один тестовый запрос разрешён. Никакой непрерывной перемотки.';}
  async function refresh(){if(!token){$('bridgeMessage').textContent='Автономный режим: расчёт работает. Для управления открой адрес из окна запущенного сервера Windows.';return;}try{const state=await api('status');updateStatus(state);$('bridgeMessage').textContent='Подключение выполняется локально через MQTTs:8883. Пароль хранится только в памяти процесса.';}catch(e){$('bridgeMessage').textContent='Сервер недоступен: '+e.message;lastState=null;validateUnload();}}
  $('connect').addEventListener('click',async()=>{const button=$('connect');button.disabled=true;try{const manual=$('manualConnection').open;const deviceId=$('devices').value;
    if(!manual&&!deviceId)throw Error('Сначала нажми «Найти принтеры» и выбери устройство либо открой ручной режим.');
    const cfg={model:$('model').value,access_code:$('accessCode').value,
      ...(manual?{host:$('host').value,serial:$('serial').value}:{device_id:deviceId})};const result=await api('connect',cfg);$('accessCode').value='';updateStatus(result);toast('MQTT подключён. Проверяем телеметрию.');await refresh();}catch(e){toast(e.message,true);}finally{button.disabled=false;}});
  $('disconnect').addEventListener('click',async()=>{try{const result=await api('disconnect',{});updateStatus(result);toast('Подключение закрыто.');}catch(e){toast(e.message,true)}});
  $('unload').addEventListener('click',async()=>{validateUnload();if($('unload').disabled)return;
    if(!confirm('ТЕСТ НА ОДНОЙ КАТУШКЕ БЕЗ СПАЙКИ.\n\nОтправить ровно ОДНУ штатную команду выгрузки на принтер? Не гарантируется движение или автоматическая остановка.'))return;
    $('unload').disabled=true;try{const data=await api('unload',{confirm:'Я НАХОЖУСЬ У ПРИНТЕРА',joined_spools:false,unit:Number($('unit').value),slot:Number($('slot').value),method:$('unloadMethod').value});toast(data.warning);await refresh();}catch(e){toast(e.message,true);}finally{setTimeout(validateUnload,600);}
  });
  ['unit','slot','noSplice','atPrinter'].forEach(id=>$(id).addEventListener('change',validateUnload));
  document.querySelectorAll('a.navlink').forEach(link=>link.addEventListener('click',e=>{e.preventDefault();document.querySelector(link.getAttribute('href'))?.scrollIntoView({behavior:'smooth'});document.querySelectorAll('a.navlink').forEach(x=>x.classList.toggle('active',x===link));}));
  estimate();drawPlans();validateUnload();refresh();if(!token){$('discover').disabled=true;$('discoveryMessage').textContent='Автономный режим: для поиска принтеров открой приложение через Windows LAN-мост.';}else{setInterval(refresh,3000);}
})();
