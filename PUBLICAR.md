# Publicar Lolcito Scout para tus amigos (una sola vez, ~15 minutos)

La idea es que las estadísticas las calcule **un solo lugar** (GitHub, gratis, todos los días, con **tu** API key guardada en secreto)
y que la app de cada amigo simplemente las descargue. Tus amigos no necesitan key: la app toma sola la cuenta con la que están
logueados en el LoL (nombre, rango y últimas partidas) y baja las estadísticas de su nivel.

```
 GitHub (todos los días, con tu key)  ──►  estadísticas publicadas  ──►  LolcitoScout.exe de cada amigo
                                                                          + su cuenta del cliente de LoL
```

## 1. Pedí la key personal de Riot (no vence)

La key de desarrollo vence cada 24 h, así que para que GitHub trabaje solo necesitás la **Personal API Key**.

1. Entrá a [developer.riotgames.com](https://developer.riotgames.com) → tu usuario → **Register Product** → **Personal API Key**.
2. Nombre: `Lolcito Scout`. Descripción (en inglés):
   > Desktop companion app for me and a small group of friends. A daily job collects ranked solo queue matches
   > from LAS and publishes aggregated champion statistics (win rates, builds, matchups). Each user's app reads only
   > their own account and the in-game data shown by the League client. No player data is shared or sold.
3. Esperá la aprobación (días o un par de semanas). Riot permite la key personal para "vos y una comunidad privada chica":
   perfecto para amigos. Si algún día lo querés publicar para todo el mundo, hay que pedir una **Production key**.

## 2. Creá el repositorio en GitHub

1. Creá una cuenta en [github.com](https://github.com) (si no tenés).
2. Instalá **GitHub Desktop** ([desktop.github.com](https://desktop.github.com)) e iniciá sesión.
3. Descomprimí `lolcito-scout.zip`. En GitHub Desktop: **File → Add local repository** → elegí la carpeta →
   te va a ofrecer "create a repository": aceptá → **Publish repository**.
   - Nombre: `lolcito-scout`
   - **Destildá "Keep this code private"** (tiene que ser público para que las apps de tus amigos puedan leer las
     estadísticas, y además es requisito para el certificado de firma barato).

## 3. Guardá tu key como secreto

En la página del repo en GitHub: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `RIOT_API_KEY`
- Secret: tu key (`RGAPI-...`)

Queda cifrada: nadie la puede ver, ni siquiera quien descargue la app.

## 4. Encendé las tareas automáticas

1. Pestaña **Actions** → si pregunta, tocá **I understand my workflows, go ahead and enable them**.
2. **Estadísticas diarias → Run workflow**. Tarda unos 30–40 minutos la primera vez. Después corre solo todos los días a las 6:00.
3. **Compilar LolcitoScout.exe → Run workflow**. En unos 5 minutos aparece el .exe en **Releases** (a la derecha
   de la página del repo), ya configurado para leer las estadísticas de tu repo.

## 5. Compartilo

Pasales a tus amigos el link: `https://github.com/TU-USUARIO/lolcito-scout/releases/latest`
Ahí descargan **LolcitoScout.exe**, lo abren y listo: no instalan nada ni cargan ninguna key.

Cada vez que cambies algo del programa, volvé a correr **Compilar LolcitoScout.exe** y el link se actualiza solo.

## Firma digital (para que Windows no muestre el aviso)

Windows muestra «Windows protegió tu PC» con cualquier programa sin firma. Para firmarlo necesitás un certificado de
firma de código a tu nombre, que emite una empresa certificadora después de verificar tu identidad (eso no lo puede
hacer nadie por vos).

- **La opción más barata para vos: Certum "Open Source Code Signing" en la nube** (desde unos €49 por año, sin
  lector de tarjetas). Es para personas y proyectos de código abierto no comerciales: tu repo público de GitHub
  cumple. Te piden documento, un comprobante de domicilio y el link al repo.
- **Azure Artifact Signing** (Microsoft, ~US$10 por mes) por ahora solo acepta personas de EE. UU. y Canadá.
- Los certificados comunes (OV) cuestan desde unos €200 por año.

Cuando tengas el certificado:
1. Instalá **SimplySign Desktop** (Certum) e iniciá sesión: el certificado aparece en Windows.
2. Instalá el **Windows SDK** (trae `signtool`).
3. Descargá el .exe de Releases, ponelo junto a `firmar.bat`, editá la línea `NOMBRE=` con el nombre de tu certificado
   y hacé doble clic. Después subí el .exe firmado al Release (arrastrándolo en **Edit release**).

Aun firmado, SmartScreen puede avisar las primeras semanas hasta que el programa junta "reputación" (descargas sin
problemas). Con el tiempo el aviso desaparece.
