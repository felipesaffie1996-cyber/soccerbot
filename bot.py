import logging
import os
import json
import asyncio
import aiohttp
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from football_api import FootballAPI
from response_builder import ResponseBuilder, _status_label
from intent_parser import IntentParser

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALLOWED_CHAT_IDS_STR = os.getenv("ALLOWED_CHAT_IDS", "")

ALLOWED_CHAT_IDS = set()
if ALLOWED_CHAT_IDS_STR:
    for cid in ALLOWED_CHAT_IDS_STR.split(","):
        cid = cid.strip()
        if cid:
            try:
                ALLOWED_CHAT_IDS.add(int(cid))
            except ValueError:
                pass

football_api = FootballAPI(FOOTBALL_API_KEY)
response_builder = ResponseBuilder()
intent_parser = IntentParser()


def is_authorized(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return chat_id in ALLOWED_CHAT_IDS


INTENT_SYSTEM_PROMPT = """Eres un extractor de intenciones para un bot de fútbol.
El usuario envía mensajes en español sobre fútbol. Tu tarea es extraer la intención y devolver SOLO un JSON válido, sin texto adicional.

Intenciones posibles:
- live_fixtures: quiere ver partidos en vivo. Puede incluir min_minute (int).
- today_fixtures: quiere ver partidos de hoy. Puede incluir league (string).
- standings: quiere tabla de posiciones. Incluir league (string).
- top_scorers: quiere goleadores. Incluir league (string).
- live_fixture_detail: quiere detalle de un partido en vivo. Incluir team1 y team2.
- fixture_stats: quiere estadísticas de un partido. Incluir team1 y team2.
- late_goals_multi: quiere goles en tiempo adicional (90+) para una o más ligas y una o más jornadas.
  Incluir leagues (array de strings) y rounds (array de ints).
  Si dice "últimas 3 fechas" y la liga tiene ~8 jornadas jugadas, inferir [6,7,8].
  Si dice "última fecha" usar el número más alto razonable.
  Si no especifica jornadas exactas pero dice "últimas N fechas", usar rounds: null y rounds_count: N.
- unknown: no se entiende la consulta.

Ejemplos:
"goles sobre el final jornada 7 primera division chile" → {"type": "late_goals_multi", "leagues": ["Primera Division Chile"], "rounds": [7]}
"cuántos goles sobre el final en chile, holanda y alemania de las últimas 3 fechas" → {"type": "late_goals_multi", "leagues": ["Primera Division Chile", "Eredivisie", "Bundesliga"], "rounds": null, "rounds_count": 3}
"goles al final jornadas 6 7 y 8 de la premier" → {"type": "late_goals_multi", "leagues": ["Premier League"], "rounds": [6, 7, 8]}
"tabla de la premier" → {"type": "standings", "league": "Premier League"}
"qué partidos hay en vivo" → {"type": "live_fixtures"}
"partidos de hoy" → {"type": "today_fixtures"}

Devuelve SOLO el JSON, sin explicaciones ni markdown."""


async def parse_intent_with_claude(text: str) -> dict:
    if not ANTHROPIC_API_KEY:
        return intent_parser.parse(text)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "system": INTENT_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": text}],
                }
            ) as resp:
                data = await resp.json()
                raw = data["content"][0]["text"].strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                intent = json.loads(raw)
                logger.info(f"Claude intent: {intent}")
                return intent
    except Exception as e:
        logger.error(f"Claude intent parsing failed: {e}, falling back to rule-based")
        return intent_parser.parse(text)


async def process_late_goals_single(league_query: str, round_number: int) -> str:
    """Process late goals for a single league + round."""
    league_id, season = await football_api.find_league(league_query)
    if not league_id:
        return f"❌ No encontré la liga: *{league_query}*"

    fixtures = await football_api.get_fixtures_by_round(league_id, season, round_number)
    if not fixtures:
        return f"❌ No encontré partidos para jornada *{round_number}* de *{league_query}*"

    results = []
    for f in fixtures:
        status_short = f["fixture"]["status"]["short"]
        if status_short not in ("FT", "AET", "PEN", "1H", "2H", "HT", "ET", "P", "LIVE"):
            results.append({
                "home": f["teams"]["home"]["name"],
                "away": f["teams"]["away"]["name"],
                "score_home": f.get("goals", {}).get("home", 0),
                "score_away": f.get("goals", {}).get("away", 0),
                "status": "No jugado",
                "late_goals": [],
            })
            continue

        fixture_id = f["fixture"]["id"]
        events = await football_api.get_fixture_events(fixture_id)
        late_goals = []
        for ev in events:
            if ev.get("type") != "Goal":
                continue
            minute = ev.get("time", {}).get("elapsed", 0) or 0
            extra = ev.get("time", {}).get("extra")
            if minute >= 90:
                late_goals.append({
                    "minute": minute,
                    "extra": extra,
                    "scorer": ev.get("player", {}).get("name", "?"),
                    "team": ev.get("team", {}).get("name", "?"),
                    "type": ev.get("detail", ""),
                })

        status_label = _status_label(status_short, f["fixture"]["status"].get("elapsed"))
        results.append({
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
            "score_home": f.get("goals", {}).get("home", 0),
            "score_away": f.get("goals", {}).get("away", 0),
            "status": status_label,
            "late_goals": late_goals,
        })

    return response_builder.build_late_goals(results, league_query, round_number)


async def get_last_n_rounds(league_query: str, n: int) -> list[int]:
    """Get the last N played round numbers for a league."""
    league_id, season = await football_api.find_league(league_query)
    if not league_id:
        return []
    available = await football_api.get_available_rounds(league_id, season)
    if not available:
        return []
    # Extract numbers from round names like "Regular Season - 7"
    import re
    numbered = []
    for r in available:
        m = re.search(r'(\d+)$', r.strip())
        if m:
            numbered.append(int(m.group(1)))
    numbered = sorted(set(numbered))
    return numbered[-n:] if len(numbered) >= n else numbered


async def handle_late_goals_multi(intent: dict, update: Update):
    """Handle multi-league, multi-round late goals query."""
    leagues = intent.get("leagues", [])
    rounds = intent.get("rounds")
    rounds_count = intent.get("rounds_count")

    if not leagues:
        await update.message.reply_text(
            "Especifica al menos una liga, por ejemplo:\n"
            "`goles sobre el final últimas 3 jornadas primera division chile`",
            parse_mode="Markdown"
        )
        return

    # If rounds_count given but not specific rounds, resolve per league
    if not rounds and rounds_count:
        await update.message.reply_text(
            f"⏳ Buscando las últimas {rounds_count} jornadas para {len(leagues)} liga(s)..."
        )
        # Get last N rounds for the first league (assume same for others)
        rounds = await get_last_n_rounds(leagues[0], rounds_count)
        if not rounds:
            await update.message.reply_text("❌ No pude determinar las últimas jornadas. Especifica los números.")
            return

    if not rounds:
        await update.message.reply_text(
            "Especifica las jornadas, por ejemplo:\n"
            "`goles sobre el final jornadas 6 7 8 primera division chile`",
            parse_mode="Markdown"
        )
        return

    total = len(leagues) * len(rounds)
    await update.message.reply_text(
        f"⏳ Analizando {len(leagues)} liga(s) × {len(rounds)} jornada(s) = {total} consulta(s)...\n"
        f"Ligas: {', '.join(leagues)}\n"
        f"Jornadas: {', '.join(str(r) for r in rounds)}"
    )

    # Process all combinations concurrently
    tasks = []
    labels = []
    for league in leagues:
        for round_num in rounds:
            tasks.append(process_late_goals_single(league, round_num))
            labels.append((league, round_num))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Send results grouped by league
    for league in leagues:
        league_results = []
        for i, (lbl_league, lbl_round) in enumerate(labels):
            if lbl_league == league:
                result = results[i]
                if isinstance(result, Exception):
                    league_results.append(f"❌ Jornada {lbl_round}: error al consultar")
                else:
                    league_results.append(result)

        # Send each league as separate message
        for msg in league_results:
            try:
                await update.message.reply_text(msg, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(msg)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")
        return
    welcome = (
        "⚽ *SoccerBot activo*\n\n"
        "Puedo responder preguntas de fútbol en tiempo real. Prueba con:\n\n"
        "• `¿Qué partidos están en vivo?`\n"
        "• `¿Partidos en minuto 80 o más?`\n"
        "• `¿Cómo va la Premier League?`\n"
        "• `Estadísticas del partido X vs Y`\n"
        "• `¿Qué partidos hay hoy?`\n"
        "• `Tabla de posiciones de La Liga`\n"
        "• `Goleadores de la Champions League`\n"
        "• `Goles sobre el final jornada 7 Primera División Chile`\n"
        "• `Goles al final últimas 3 fechas en chile, holanda y alemania`\n\n"
        "Datos en vivo de API-Football ✅"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    help_text = (
        "📖 *Comandos disponibles:*\n\n"
        "/start — Mensaje de bienvenida\n"
        "/live — Partidos en vivo ahora\n"
        "/today — Todos los partidos de hoy\n"
        "/standings [liga] — Tabla de posiciones\n"
        "/top [liga] — Goleadores\n"
        "/help — Esta ayuda\n\n"
        "Escribe en lenguaje natural:\n"
        "• `¿Qué partidos se juegan hoy en Europa?`\n"
        "• `¿Cómo quedó el clásico?`\n"
        "• `Goles al final últimas 3 fechas chile y alemania`\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def live_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    await update.message.reply_text("⏳ Consultando partidos en vivo...")
    try:
        fixtures = await football_api.get_live_fixtures()
        text = response_builder.build_live_fixtures(fixtures)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /live: {e}")
        await update.message.reply_text("❌ Error al consultar la API. Intenta de nuevo.")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    await update.message.reply_text("⏳ Consultando partidos de hoy...")
    try:
        fixtures = await football_api.get_today_fixtures()
        text = response_builder.build_today_fixtures(fixtures)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /today: {e}")
        await update.message.reply_text("❌ Error al consultar la API. Intenta de nuevo.")


async def standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    league_query = " ".join(context.args) if context.args else None
    if not league_query:
        await update.message.reply_text(
            "Especifica una liga, por ejemplo:\n`/standings Premier League`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(f"⏳ Buscando tabla de {league_query}...")
    try:
        league_id, season = await football_api.find_league(league_query)
        if not league_id:
            await update.message.reply_text(f"❌ No encontré la liga: *{league_query}*", parse_mode="Markdown")
            return
        standings = await football_api.get_standings(league_id, season)
        text = response_builder.build_standings(standings, league_query)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /standings: {e}")
        await update.message.reply_text("❌ Error al consultar la API.")


async def top_scorers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    league_query = " ".join(context.args) if context.args else None
    if not league_query:
        await update.message.reply_text(
            "Especifica una liga, por ejemplo:\n`/top Champions League`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(f"⏳ Buscando goleadores de {league_query}...")
    try:
        league_id, season = await football_api.find_league(league_query)
        if not league_id:
            await update.message.reply_text(f"❌ No encontré la liga: *{league_query}*", parse_mode="Markdown")
            return
        scorers = await football_api.get_top_scorers(league_id, season)
        text = response_builder.build_top_scorers(scorers, league_query)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /top: {e}")
        await update.message.reply_text("❌ Error al consultar la API.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        logger.warning(f"Unauthorized message from chat_id: {chat_id}")
        return
    user_text = update.message.text.strip()
    if not user_text:
        return
    logger.info(f"Message from {chat_id}: {user_text}")

    intent = await parse_intent_with_claude(user_text)
    logger.info(f"Detected intent: {intent}")

    await update.message.reply_text("⏳ Consultando datos...")

    try:
        if intent["type"] == "late_goals_multi":
            await handle_late_goals_multi(intent, update)
            return

        elif intent["type"] == "live_fixtures":
            fixtures = await football_api.get_live_fixtures(min_minute=intent.get("min_minute"))
            text = response_builder.build_live_fixtures(fixtures, min_minute=intent.get("min_minute"))

        elif intent["type"] == "live_fixture_detail":
            fixtures = await football_api.get_live_fixtures()
            fixture = _find_fixture(fixtures, intent.get("team1"), intent.get("team2"))
            if fixture:
                fixture_id = fixture["fixture"]["id"]
                stats = await football_api.get_fixture_stats(fixture_id)
                events = await football_api.get_fixture_events(fixture_id)
                lineups = await football_api.get_fixture_lineups(fixture_id)
                text = response_builder.build_fixture_detail(fixture, stats, events, lineups)
            else:
                text = "❌ No encontré un partido en vivo con esos equipos."

        elif intent["type"] == "today_fixtures":
            fixtures = await football_api.get_today_fixtures(league_query=intent.get("league"))
            text = response_builder.build_today_fixtures(fixtures, league_filter=intent.get("league"))

        elif intent["type"] == "standings":
            league_query = intent.get("league", "")
            league_id, season = await football_api.find_league(league_query)
            if not league_id:
                text = f"❌ No encontré la liga: *{league_query}*"
            else:
                standings = await football_api.get_standings(league_id, season)
                text = response_builder.build_standings(standings, league_query)

        elif intent["type"] == "top_scorers":
            league_query = intent.get("league", "")
            league_id, season = await football_api.find_league(league_query)
            if not league_id:
                text = f"❌ No encontré la liga: *{league_query}*"
            else:
                scorers = await football_api.get_top_scorers(league_id, season)
                text = response_builder.build_top_scorers(scorers, league_query)

        elif intent["type"] == "fixture_stats":
            team1 = intent.get("team1")
            team2 = intent.get("team2")
            fixtures = await football_api.get_live_fixtures()
            fixture = _find_fixture(fixtures, team1, team2)
            if not fixture:
                today_fixtures = await football_api.get_today_fixtures()
                fixture = _find_fixture(today_fixtures, team1, team2)
            if fixture:
                fixture_id = fixture["fixture"]["id"]
                stats = await football_api.get_fixture_stats(fixture_id)
                events = await football_api.get_fixture_events(fixture_id)
                text = response_builder.build_fixture_stats(fixture, stats, events)
            else:
                text = "❌ No encontré el partido solicitado."

        else:
            text = (
                "No entendí tu consulta. Puedes preguntarme:\n\n"
                "• `¿Qué partidos están en vivo?`\n"
                "• `¿Partidos en minuto 80+?`\n"
                "• `¿Cómo va la Premier League?`\n"
                "• `Tabla de La Liga`\n"
                "• `Goleadores Champions League`\n"
                "• `Goles al final últimas 3 fechas chile y alemania`\n\n"
                "O usa /help para ver todos los comandos."
            )

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text("❌ Ocurrió un error al procesar tu consulta. Intenta de nuevo.")


def _find_fixture(fixtures: list, team1: str, team2: str) -> dict | None:
    if not team1:
        return None
    for f in fixtures:
        home = f["teams"]["home"]["name"].lower()
        away = f["teams"]["away"]["name"].lower()
        t1 = team1.lower()
        t2 = (team2 or "").lower()
        if t1 in home or t1 in away:
            if not t2 or t2 in home or t2 in away:
                return f
    return None


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("live", live_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("standings", standings_command))
    app.add_handler(CommandHandler("top", top_scorers_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("SoccerBot iniciado ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
