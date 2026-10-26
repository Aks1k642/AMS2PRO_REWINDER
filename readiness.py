"""Human-readable connection/unload readiness: one source of truth for UI and API."""
import time


def _flag_number(value):
    if value is None:
        return None
    try:
        if isinstance(value, int):
            return value
        text = str(value).strip()
        return int(text, 16) if text.startswith("0x") or any(c in "abcdefABCDEF" for c in text) else int(text)
    except (TypeError, ValueError):
        return None


def evaluate(connected, telemetry, last_seen, selected_tray=None, last_sent=None):
    failures, warnings = [], []

    def block(code, message, action):
        failures.append({"code": code, "message": message, "action": action})

    def warn(code, message, action):
        warnings.append({"code": code, "message": message, "action": action})

    if not connected:
        block("no_connection", "Нет MQTT-соединения с принтером",
              "Найди принтер, введи LAN Access Code и нажми «Подключиться».")
        return {"ready": False, "stage": "disconnected", "blockers": failures, "warnings": warnings}

    age = None if last_seen == 0 else round(time.monotonic() - last_seen, 1)
    if age is None or age > 20:
        block("telemetry", "Нет актуального ответа о состоянии принтера",
              "Подожди обновления телеметрии, проверь LAN/Developer Mode и MQTT-подписку.")
        return {"ready": False, "stage": "waiting_status", "blockers": failures, "warnings": warnings}

    state = str(telemetry.get("gcode_state") or "").upper()
    if state not in ("IDLE", "FINISH"):
        block("printer_state", "Состояние печати: " + (state or "неизвестно"),
              "Дождись завершения печати и перехода в ожидание.")

    flags = _flag_number(telemetry.get("fun"))
    if flags is None:
        warn("control_unknown", "Разрешение LAN-команд не подтверждено телеметрией",
             "Проверь Developer Mode на принтере; MQTT-соединение само по себе не означает доступ к управлению.")
    elif flags & 0x20000000:
        block("developer_mode", "Прошивка требует подписанные команды управления",
              "Включи Developer Mode для локального управления, затем переподключись.")

    ams_status = _flag_number(telemetry.get("ams_status"))
    if ams_status is None:
        warn("ams_status_missing", "AMS не сообщает текущий режим работы",
             "Проверь подключение AMS и обновление состояния на экране принтера.")
    elif ams_status >> 8 not in (0, 3):
        block("ams_busy", "AMS занят: код " + str(ams_status),
              "Дождись окончания работы AMS и повтори проверку.")

    ams = telemetry.get("ams") if isinstance(telemetry.get("ams"), dict) else {}
    tray_value = ams.get("tray_now")
    try:
        tray_now = int(str(tray_value), 0)
    except (TypeError, ValueError):
        try:
            tray_now = int(str(tray_value))
        except (TypeError, ValueError):
            tray_now = None
    if tray_now is None:
        block("tray_unknown", "Неизвестен активный слот AMS",
              "Загрузи обычную катушку в тракт и запроси полное состояние принтера.")
    elif tray_now in (254, 255):
        block("tray_unloaded", "Пруток AMS не находится в тракте принтера (tray_now=" + str(tray_now) + ")",
              "Загрузи филамент из нужного AMS-слота перед пробной выгрузкой.")
    elif selected_tray is not None and tray_now != selected_tray:
        block("tray_mismatch", f"Выбран слот {selected_tray}, а в тракте {tray_now}",
              "Выбери в приложении слот, который показывает принтер, либо загрузи нужный филамент.")

    if last_sent is not None and time.monotonic() - last_sent < 30:
        block("cooldown", "После предыдущей команды действует пауза безопасности (30 секунд)",
              "Дождись ответа принтера и окончания операции перед следующим запросом.")

    return {"ready": not failures, "stage": "ready" if not failures else "needs_attention",
            "blockers": failures, "warnings": warnings, "tray_now": tray_now, "telemetry_age_s": age}
