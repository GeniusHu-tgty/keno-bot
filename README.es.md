# Keno BOT

[![lang](https://img.shields.io/badge/English-blue.svg)](README.md)
[![lang](https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-red.svg)](README.zh-CN.md)
[![lang](https://img.shields.io/badge/%E6%97%A5%E6%9C%AC%E8%AA%9E-green.svg)](README.ja.md)
[![lang](https://img.shields.io/badge/Espa%C3%B1ol-brightgreen.svg)](#)
[![lang](https://img.shields.io/badge/%D0%A0%D1%83%D1%81%D1%81%D0%BA%D0%B8%D0%B9-purple.svg)](README.ru.md)
[![lang](https://img.shields.io/badge/%ED%95%9C%EA%B5%AD%EC%96%B4-yellow.svg)](README.ko.md)

[![License: GPL v2](https://img.shields.io/badge/license-GPLv2-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#inicio-r%C3%A1pido)
[![Tests](https://img.shields.io/badge/tests-110%20passing-brightgreen.svg)](CONTRIBUTING.md)

**Keno BOT** es un banco de pruebas local y un bot de apuestas automáticas **solo para Keno**.

* Recalcula en local toda la cadena de **juego justo verificable** (`server_seed` / `client_seed` / `nonce`, HMAC-SHA256) y coincide byte a byte con la calculadora oficial: puedes comprobarlo tú mismo con un solo comando.
* Audita las **40 combinaciones de tabla de pagos** oficiales, una por una (RTP medido 98.65% – 99.07%).
* Mide estrategias con un **modelo nulo** (distribución hipergeométrica justa), así que ves la **forma de la distribución de resultados**, no una captura de pantalla con ganancias.
* Solo si tú lo activas, puede operar **tu propia cuenta** a través de **tu propio Chrome** (CDP). Por defecto es simulación pura; el dinero real requiere habilitarlo explícitamente.

Solo Keno. No predice, no elige números con IA y no promete ningún beneficio.

![Banco de pruebas de Keno BOT](docs/images/lab.png)

---

## En qué se diferencia de los scripts de Keno habituales

| Script habitual | Keno BOT |
| --- | --- |
| Un martillo: números calientes, perseguir fríos, martingala | Primero una regla de medir: RTP por apuesta, varianza y valor esperado calculados en local |
| Pagos transmitidos de boca en boca | Las 40 combinaciones oficiales recalculadas y comparadas con la tabla propia |
| El RNG solo se puede «confiar» | Cadena HMAC-SHA256 recalculada en local, byte a byte contra la calculadora oficial |
| Las pruebas son capturas de pantalla | Libro completo en todos los modos: volumen, retorno, drawdown, rachas, percentiles |
| Solo clics manuales | Escalera de importes + disciplina de sesión + refrigerios por tramos + stop-loss/take-profit, totalmente automático |

## Inicio rápido

### A. Ejecutar el exe (sin instalar Python)

1. Descarga `KenoBOT.exe` desde [Releases](../../releases).
2. Haz doble clic: levanta una página local en `127.0.0.1` y abre el navegador solo.
3. Dos pantallas: `/` es el banco de pruebas (simulación pura) y `/live` es la mesa real (el dinero solo se mueve tras conectar y activar los interruptores).

En la primera ejecución crea `%LOCALAPPDATA%\KenoBOT` para estado, registros e informes. No toca el registro de Windows ni instala servicios; borrar la carpeta equivale a borrarlo todo.

### B. Ejecutar desde el código (desarrolladores)

```bash
git clone <your-fork-url> keno-bot && cd keno-bot
python -m pip install -e .
python keno_bot_app.py        # equivale a python -m keno.cli serve
```

En Windows también puedes hacer doble clic en `启动.bat`: usa `dist\KenoBOT.exe` si existe y, si no, arranca con el Python local.

### C. Compilar tu propio exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1            # archivo único dist\KenoBOT.exe
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onedir   # versión de carpeta, arranca más rápido
powershell -ExecutionPolicy Bypass -File tools\make_release.ps1  # exe + documentación -> dist\KenoBOT-<version>-win64.zip
```

## Cómo conectar la mesa real (dinero real, desactivado por defecto)

Keno BOT no guarda tus credenciales ni tiene su propio formulario de acceso. Hace una sola cosa: se conecta al Chrome donde **ya has iniciado sesión** (Chrome DevTools Protocol), toma el token de sesión de las propias peticiones de la página (solo en memoria, nunca en disco) y pulsa los botones de apuesta como lo haría una persona.

```bash
# 1) Arranca Chrome con el puerto de depuración (tu propio perfil)
chrome.exe --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\keno-chrome-profile

# 2) Inicia sesión a mano en ese Chrome y abre la página de Keno

# 3) Comprobación de solo lectura: conectar y mirar, sin apostar
python -m keno.cli live connect --cdp http://127.0.0.1:9222

# 4) Solo si de verdad quieres apostar: añade --live-bets y empieza por la apuesta mínima
python -m keno.cli live run --cdp http://127.0.0.1:9222 --live-bets --risk low --pick-count 10 --rounds 20
```

`KENO_CHROME_PROFILE` / `KENO_CHROME_PS1` permiten fijar el perfil de Chrome y el script de arranque; si no se definen se usan los valores por defecto bajo `~/.keno-bot/`.

La disciplina está en el código, no en la documentación: tope por apuesta, escalones, bajar de nivel tras dos derrotas seguidas, descanso obligatorio tras ganar en el cuarto escalón, stop-loss/take-profit, refrigerio entre tramos y límite diario.

![Mesa real de Keno BOT](docs/images/live.png)

## Juego justo verificable (recálculo local byte a byte)

Cada ronda se puede recomputar a partir de tres valores públicos: `server_seed` (primero se publica el hash y luego se revela la semilla), `client_seed` (lo puedes cambiar) y `nonce` (número de ronda).

```bash
# Muestra de autocomprobación incluida (240 rondas, semillas solo de este repositorio)
python -m keno.cli verify-rounds --replay-file data/samples/rounds_sample.jsonl --seeds-file data/samples/seeds_sample.json
```

La salida esperada es `240/240 rounds PASS`. Cambia un carácter de una semilla y pasa a FAIL al instante: eso demuestra que de verdad está verificando y no simulando el proceso.

## Auditoría de la tabla de pagos

| Variante | RTP medido |
| --- | --- |
| low, 10 números | 98.76% |
| Las 40 combinaciones | 98.65% – 99.07% |

La tabla propia `configs/payout.yaml` y la oficial difieren en 5/6/7/8/9 aciertos; la lista completa está en `reports/payout_audit.md`. Para recalcularlo tú mismo:

```bash
python -m keno.cli audit-payouts --paytable configs/payout.yaml --official data/reference/stake_keno_payouts_official.json
```

## Qué mide esta herramienta

* **Valor esperado de cualquier variante**: `pago × P(acierto) − apuesta`, calculado directamente con la hipergeométrica, sin simulación.
* **Varianza y drawdown de una estrategia de bankroll**: Monte Carlo sobre sorteos justos, con semilla fija y resultados reproducibles.
* **Rachas y distribución de aciertos**: comparadas con la teoría (chi-cuadrado sobre el histograma de aciertos).
* **Validación con parámetros congelados**: parámetros ajustados en un tramo se reproducen sobre material de semillas nunca visto para confirmar que no memorizaron ruido.

Keno paga menos de lo que apuestas en todas sus variantes. La gestión de bankroll solo cambia la **forma** de la distribución (drawdown, velocidad de ruina, volatilidad), nunca el signo. El valor de este repositorio es cuantificarlo, no contarlo como una historia.

## Estructura del proyecto

```text
keno_bot_app.py           lanzador / entrada de PyInstaller
build_exe.ps1             compilación del exe
configs/                  game.yaml (tablero, protocolo RNG) payout.yaml (pagos propios) bot_phase.yaml (escalones)
data/reference/           tabla de pagos oficial
data/samples/             muestras de autocomprobación
src/keno/provably_fair/   HMAC-SHA256, generación de flotantes, verificación por ronda
src/keno/game/            sorteo, aciertos, pagos, liquidación
src/keno/bot/             bot: bankroll, máquina de fases, estrategia de combinaciones, libro, CDP/ejecución real
src/keno/research/        Monte Carlo, validación congelada, rejilla de riesgo
src/keno/reporting/       métricas (hipergeométrica, chi-cuadrado, drawdown, rachas) y exportación
src/keno/webapp/          mesa de trabajo local (servidor HTTP + páginas)
tools/                    generar muestras, iconos y releases
docs/                     arquitectura, método de verificación, inicio rápido en chino
tests/                    pytest (110 pruebas)
```

## Hoja de ruta (PRs bienvenidas)

* **Plugins de estrategia por script**: un punto de enganche estable (recibe historial y saldo, devuelve números e importe) para que cualquiera aporte lógica sin tocar el núcleo.
* **Conciliación con la lista de apuestas**: tras un fallo o un timeout, revisar la lista de apuestas de la plataforma para cuadrar el libro.
* **Interfaz en inglés**: los textos de las páginas están sobre todo en chino; con i18n serán más cómodos para colaboradores internacionales.
* **Validación de datos**: JSON Schema para `data/**/*.jsonl` y comprobaciones de campos en `collect`.
* **Limpieza multiplataforma**: concentrar las rutas personales en `keno/paths.py` y variables de entorno (macOS/Linux incluidos).
* **Fuente WebSocket real**: `src/keno/bot/ws.py` es hoy solo un esqueleto.

## Aviso

Keno es un juego de esperanza negativa. Este repositorio es un proyecto de investigación e ingeniería: mide, no predice, y no promete resultados. Usa solo dinero que puedas perder y respeta la ley de tu jurisdicción y los términos de la plataforma.

## Licencia

**GNU General Public License v2.0**, ver [`LICENSE`](LICENSE). Copyright (C) 2026 GeniusHu-tgty. Tal como dice la licencia, se ofrece sin garantía alguna. Puedes usarlo, estudiarlo, compartirlo y modificarlo, incluso comercialmente; si distribuyes una versión modificada, debe seguir siendo GPL y acompañarse del código fuente.
