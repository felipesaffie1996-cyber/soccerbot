# ⚽ SoccerBot — Bot de Telegram con datos de fútbol en tiempo real

Bot de Telegram que responde preguntas de fútbol usando [API-Football](https://www.api-football.com/).

## Funcionalidades

| Consulta | Ejemplo |
|---|---|
| Partidos en vivo | `¿Qué partidos están en vivo?` |
| Minuto específico | `¿Partidos en el minuto 80 o más?` |
| Partidos de hoy | `¿Qué partidos hay hoy?` |
| Tabla de posiciones | `¿Cómo va la Premier League?` / `/standings La Liga` |
| Goleadores | `Goleadores de la Champions League` / `/top Serie A` |
| Detalle de partido | `¿Cómo va el Chelsea vs Arsenal?` |
| Estadísticas | `Estadísticas Real Madrid vs Barcelona` |

## Comandos

- `/start` — Bienvenida
- `/live` — Partidos en vivo
- `/today` — Partidos de hoy
- `/standings [liga]` — Tabla de posiciones
- `/top [liga]` — Goleadores
- `/help` — Ayuda

## Deploy en Railway

### 1. Subir el código

```bash
# Inicializa git y sube a GitHub
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/tu-usuario/soccerbot.git
git push -u origin main
```

### 2. Crear proyecto en Railway

1. Ve a [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
2. Selecciona tu repositorio

### 3. Configurar variables de entorno

En Railway → tu proyecto → **Variables**, agrega:

```
TELEGRAM_TOKEN=8760870045:AAHXGZJGXHTsuLukgWYnVv34bLDZd21RZA4
FOOTBALL_API_KEY=7aa252fd9c63236a40e473bb6d518319
ALLOWED_CHAT_IDS=TU_CHAT_ID_1,TU_CHAT_ID_2
```

### 4. Obtener tu Chat ID

Para obtener el ID de un chat autorizado:
1. Despliega el bot **sin** `ALLOWED_CHAT_IDS` configurado (o con valor vacío)
2. Escríbele `/start` al bot desde el chat que quieres autorizar
3. En los logs de Railway verás: `Unauthorized access attempt from chat_id: 123456789`
4. Copia ese número y ponlo en `ALLOWED_CHAT_IDS`

Alternativamente, usa [@userinfobot](https://t.me/userinfobot) para obtener tu ID personal.

### 5. Verificar deploy

En Railway → **Deployments** → verifica que los logs muestren:
```
SoccerBot iniciado ✅
```

## Estructura del proyecto

```
soccerbot/
├── bot.py              # Punto de entrada, handlers de Telegram
├── football_api.py     # Cliente de API-Football (async)
├── intent_parser.py    # Parser de lenguaje natural → intención
├── response_builder.py # Formateador de respuestas para Telegram
├── requirements.txt
├── Procfile            # Comando de inicio para Railway
└── .env.example        # Variables de entorno de ejemplo
```

## Ligas soportadas (detección automática)

El bot reconoce por nombre en español/inglés:
- Premier League, La Liga, Bundesliga, Serie A, Ligue 1
- Champions League, Europa League, Conference League
- Copa Libertadores, Copa Sudamericana
- Ligas de Argentina, Chile, Brasil, México
- MLS, Copa América, Euro, World Cup
- Y cualquier liga buscando directamente en la API

## Notas importantes

- **Sin invención de datos**: Si la API no devuelve datos, el bot lo indica claramente
- **Rate limiting**: El plan MEGA tiene 150,000 req/día; el bot loguea el quota restante en cada llamada
- **Grupo cerrado**: Solo responde a los `chat_id` en `ALLOWED_CHAT_IDS`; los demás son silenciados
