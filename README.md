# Lolcito Scout — mejores picks del día para ADC y Support (LAS, Platino–Esmeralda)

Todos los días escautea partidas rankeds reales de jugadores Platino y Esmeralda de LAS, y arma un reporte con:

- **Top 5 ADC y Support del día** y tier list completa (S/A/B/C/D) con winrate, pick rate, ban rate y KDA.
- **Build por campeón**: ítems más armados, botas, runa principal y hechizos, con el winrate de cada uno.
- **Enfrentamientos**: a quién le gana y contra quién le cuesta cada campeón.
- **Mejores dúos ADC + Support**.
- **Asistente de draft**: elegís tu rol, el rival de línea y/o tu compañero de bot y te recomienda picks.
- **Tu pool** (opcional): tus campeones con tu winrate y el tier que tienen en el meta.
- **Asistente en vivo**: en la selección te dice contra quién vas y qué te conviene pickear; en la partida te va sugiriendo ítems según lo que compra el equipo rival (ver sección 5).

El reporte es una página HTML que se abre con doble clic: `reportes/ultimo.html`.

---

## 0. La forma fácil: LolcitoScout.exe

Doble clic en **LolcitoScout.exe**: no hace falta instalar nada ni cargar ninguna API key.

- **Tu cuenta se detecta sola** desde el cliente de LoL (nombre, rango y tus últimas partidas).
- **Las estadísticas se descargan solas** de acuerdo a tu rango (Hierro–Plata, Oro–Platino o Esmeralda–Maestro).
  Las calcula todos los días un proceso automático en GitHub con la key del dueño del proyecto: ver **PUBLICAR.md**.
- Pestañas: **En vivo** (selección y partida, tu equipo a la izquierda y el rival a la derecha), **Estadísticas** y **Configuración**.

Los datos se guardan en `%LOCALAPPDATA%\LolcitoScout`.

Tipografía: el logo es una imagen hecha con League. Títulos: Beaufort for LOL si está instalada; si no, Cinzel (incluida).
Texto: Hanken Grotesk (incluida). Las fuentes incluidas son libres (licencia OFL).

## 1. Instalar (solo si querés usar el código fuente)

1. Instalá **Python 3.10 o más nuevo** desde [python.org](https://www.python.org/downloads/) (en Windows, tildá *"Add Python to PATH"*).
2. Abrí una terminal en esta carpeta y ejecutá:
   ```
   pip install -r requirements.txt
   ```
3. Probá que todo funcione **sin API key**, con partidas simuladas:
   ```
   python main.py demo --abrir
   ```
   (Los datos del demo son inventados; sirve solo para ver cómo queda el reporte).

## 2. Sacar tu API key de Riot

Hay dos tipos de key:

| Tipo | Cómo se consigue | Dura | Para qué sirve |
|---|---|---|---|
| **Development** | Automática al entrar | **24 horas** | Para probar hoy mismo |
| **Personal** | Registrando un producto (aprobación manual) | **No vence** | Para que corra solo todos los días |

**Key de desarrollo (5 minutos):**

1. Entrá a [developer.riotgames.com](https://developer.riotgames.com) e iniciá sesión con tu cuenta de Riot (la misma del LoL).
2. Aceptá los términos. En el panel vas a ver **"Development API Key"**: tocá *Regenerate API Key* y copiala (empieza con `RGAPI-`).
3. Copiá el archivo `.env.example`, renombralo a `.env` y pegá la key:
   ```
   RIOT_API_KEY=RGAPI-tu-key
   MY_RIOT_ID=TuNombre#LAS
   ```

**Key personal (para que funcione solo todos los días):**

1. En el portal, arriba a la derecha: tu usuario → **"Register Product"** → elegí **"Personal API Key"**.
2. Completá:
   - **Product name**: `Lolcito Scout`
   - **Description** (en inglés), por ejemplo:
     > Personal tool that analyzes ranked solo queue matches from Platinum–Emerald players in LAS to compute champion win rates, builds, matchups and bot lane synergies for my own use. Data is stored locally and not shared or sold.
   - **Product URL**: podés poner el repositorio de GitHub si lo subís, o dejarlo en blanco si no lo pide.
3. Enviá y esperá la aprobación (suele tardar desde unos días hasta un par de semanas). Mientras tanto usá la de desarrollo, regenerándola cada día.
4. Cuando te la aprueben, reemplazá la key en `.env`. Mantiene los mismos límites (20 pedidos por segundo, 100 cada 2 minutos), que es para lo que ya está preparada la app.

> Nunca compartas la key ni subas el archivo `.env` a internet (ya está en `.gitignore`).

## 3. Usar

```
python main.py diario --abrir     # escautea partidas nuevas y abre el reporte
python main.py reporte --abrir    # solo regenera el reporte con lo guardado
python main.py diario --parche 16.18
```

Cada corrida diaria baja hasta ~500 partidas nuevas (tarda 10–15 minutos por los límites de la API). Las partidas se acumulan en `data/lolscout.db`, así que **los números se vuelven más confiables con cada día que corre**. El reporte usa siempre el parche más nuevo; si recién salió un parche y hay pocas partidas, suma el anterior.

Se puede ajustar en `.env`: cuántos jugadores revisar, cuántas partidas bajar, el mínimo de partidas para aparecer en el ranking (`MIN_GAMES`), y hasta cambiar de rango (`TIERS=DIAMOND`) o de rol (`ROLES=MIDDLE`).

## 4. Que corra solo todos los días (Windows)

1. Abrí **Programador de tareas** (buscalo en el menú Inicio).
2. **Crear tarea básica…** → nombre `Lolcito Scout` → **Diariamente** → elegí una hora en la que la PC esté prendida (por ejemplo 12:00).
3. Acción: **Iniciar un programa** → Programa: buscá el archivo `ejecutar_diario.bat` de esta carpeta.
4. En *Iniciar en*, poné la ruta de esta carpeta. Finalizar.

Cada ejecución deja un registro en `data/ultimo_log.txt`. El reporte actualizado queda siempre en `reportes/ultimo.html` (y uno por fecha para comparar días).

## 5. Asistente en vivo (selección de campeones y partida)

```
python main.py vivo          (o doble clic en asistente_en_vivo.bat)
```

Se abre una página en el navegador (`http://localhost:8765`) que se conecta sola al cliente de LoL y se actualiza cada 2 segundos:

**En la selección de campeones**
- Tu rol, tu **rival probable de línea** (deduce el rol de cada pick rival según en qué posición se juega ese campeón en tu rango) y tu compañero de bot.
- **5 opciones para pickear**, ordenadas por winrate en tu rango ajustado por el enfrentamiento contra tu rival y la sinergia con tu compañero, con el motivo de cada una y la build base (runa, 3 ítems, botas).
- Si ya marcaste un campeón, te muestra cómo le va a ese pick contra lo que tienen enfrente.
- Descarta automáticamente los campeones baneados o ya elegidos.

**En la partida**
- Tu rival de línea con su KDA y el oro que lleva en ítems.
- **Próxima compra: 3 opciones** que se recalculan a medida que los rivales compran. Parte de los ítems que de verdad arma tu campeón en tu rango y los reordena según el equipo rival:
  - mucha curación → Heridas Graves
  - rivales con armadura / resistencia mágica → penetración
  - daño mayormente mágico o físico → la defensa que corresponde (incluidas las botas)
  - un asesino adelantado → ítems anti-burst (Ángel Guardián, escudos)
  - mucho control o mucho crítico → sus contras
- Cuánto cuesta cada opción y si **te alcanza el oro** que tenés ahora.
- Tu build base con lo que ya completaste, las amenazas del equipo rival y los dos equipos con ítems, KDA y oro en ítems (marca al rival más fuerte).

**Para verlo mientras jugás**
- Poné el juego en **modo "Sin bordes"** (Opciones → Video) y dejá la página en un segundo monitor o con Alt+Tab.
- O en el **celular**: `python main.py vivo --lan` y abrí desde el celular la dirección que aparece (tiene que estar en la misma red WiFi). Windows puede pedir permiso de firewall la primera vez: aceptá para redes privadas.

**Probarlo sin abrir el LoL:** `python main.py vivo --simular draft` o `python main.py vivo --simular partida` (usa datos de demo).

**Cómo se conecta:** usa las dos APIs locales oficiales del juego: la del cliente (lee el archivo `lockfile` de la carpeta del LoL) y la *Live Client Data API* (puerto 2999). No usa internet ni la API key, no lee la memoria del juego ni lo modifica. Es el mismo método que usan apps conocidas como Porofessor o Blitz. Si instalaste el LoL en otra carpeta, poné `LOL_PATH=D:\Juegos\Riot Games\League of Legends` en el `.env` (o instalá `psutil`, que lo encuentra solo).

**Reglas de Riot:** Riot permite apps de terceros siempre que usen solo información que el juego ya te muestra y que presenten opciones en vez de decidir por vos. Por eso el asistente usa solo lo visible en la selección y en el marcador (Tab), no mira el historial ni la identidad de los rivales y siempre muestra varias opciones con sus motivos. Si le agregás cosas, que no muestren información que el juego no te da (por ejemplo, timers de hechizos o de la jungla rival).

## Cómo se calcula

- **Winrate ajustado**: a cada campeón se le suman 30 partidas "fantasma" al 50% antes de ordenar. Así, uno que ganó 8 de 10 no queda por encima de uno que ganó 540 de 1000. El tier sale de ese valor: S ≥ 52,5 %, A ≥ 51 %, B ≥ 49,5 %, C ≥ 48 %.
- Se descartan remakes y partidas de menos de 15 minutos.
- El rol sale del `teamPosition` que asigna Riot (BOTTOM = ADC, UTILITY = Support).
- Los ítems son los que el jugador tenía al final de la partida (la API no da el orden de compra sin pedir la línea de tiempo, que cuesta un pedido extra por partida).

## Estructura

```
main.py               comandos (diario / escautear / reporte / demo)
lolscout/config.py    configuración (.env)
lolscout/riot.py      cliente de la API con control de límites y reintentos
lolscout/ddragon.py   nombres e imágenes oficiales de campeones, ítems y runas (Data Dragon)
lolscout/collect.py   escauteo de jugadores y partidas
lolscout/db.py        base de datos SQLite
lolscout/analyze.py   estadísticas: tier list, builds, counters, dúos
lolscout/report.py    reporte HTML interactivo
lolscout/demo.py      partidas simuladas para probar
lolscout/live/        asistente en vivo (conexión al cliente, lógica de picks e ítems, página)
```

## Ideas para seguir

- Orden de compra real y primer ítem (con `match-v5 timeline`).
- Bot de Discord o Telegram que mande el top del día.
- Una web pública con los reportes (para eso necesitás una *Production key*, que Riot aprueba si el producto está funcionando).

*Lolcito Scout no está respaldado por Riot Games y no refleja las opiniones de Riot Games ni de nadie oficialmente involucrado en la producción o gestión de League of Legends.*
