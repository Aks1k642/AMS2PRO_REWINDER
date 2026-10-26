# AMS 2 Pro Rewinder Lab v0.1.0

Experimental preview, **not officially supported by Bambu Lab**. Compatible profiles for H2S, P2S, X2D; compatibility of AMS 2 Pro with native unload is not a validation of continuous rewinding.

- **Windows** `AMS2ProRewinder-Windows-x64.exe`: self-contained desktop LAN bridge with web UI. No Python installation needed. Windows may show a SmartScreen warning for an unsigned application. Only use it on a trusted local network.
- **Android** `AMS2ProRewinder-Android-debug.apk`: unsigned/debug WebView client with offline planner. **For printer control it needs the Windows bridge running on the same LAN**; it does not operate the AMS from Android directly.
- Planner: filament density, approximate length/mass, spool capacity, saved plans and CSV export.
- Experimental one-shot standard filament unload via LAN MQTT, gated by explicit confirmation and printer telemetry. No automated repeated unload.

**DO NOT connect two spools or use a splicer during initial tests.** There is no verified continuous winding, length feedback, torque protection, or guaranteed remote emergency stop. Stay physically at the printer for all motor tests. The debug APK is not Play Store signed.

Release assets are built by GitHub Actions. The application has not been hardware-tested on H2S, P2S or X2D.

### Улучшение запуска Windows

При запуске приложения можно выбрать свободный HTTP-порт (последний выбор сохраняется); поддерживаются `--port 8899`, `--auto-port` и `--no-port-prompt`. Порт MQTT принтера (8883) не меняется.
