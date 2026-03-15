import logging
import os
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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8760870045:AAHXGZJGXHTsuLukgWYnVv34bLDZd21RZA4")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "7aa252fd9c63236a40e473bb6d518319")
ALLOWED_CHAT_IDS_STR = os.getenv("ALLOWED_CHAT_IDS", "")

# Parse allowed chat IDs (comma-separated in env var)
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
    """Check if a chat is authorized to use the bot."""
    if not ALLOWED_CHAT_IDS:
        # If no whitelist configured, allow all (useful during initial setup)
        return True
    return chat_id in ALLOWED_CHAT_IDS


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
        "• `Goleadores de la Champions League`\n\n"
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
        "También puedes escribir en lenguaje natural:\n"
        "• `¿Qué partidos están en vivo en el minuto 80?`\n"
        "• `¿Cómo va el Chelsea vs Arsenal?`\n"
        "• `Dame los goles del partido X`\n"
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

    # Parse intent from natural language
    intent = intent_parser.parse(user_text)
    logger.info(f"Detected intent: {intent}")

    await update.message.reply_text("⏳ Consultando datos...")

    try:
        if intent["type"] == "late_goals":
            league_query = intent.get("league", "")
            round_number = intent.get("round")

            if not league_query:
                await update.message.reply_text(
                    "Especifica la liga y la jornada, por ejemplo:\n"
                    "`goles sobre el final jornada 7 Primera División Chile`",
                    parse_mode="Markdown"
                )
                return

            league_id, season = await football_api.find_league(league_query)
            if not league_id:
                text = f"❌ No encontré la liga: *{league_query}*"
                await update.message.reply_text(text, parse_mode="Markdown")
                return

            if not round_number:
                # Ask user to specify a round
                rounds = await football_api.get_available_rounds(league_id, season)
                text = response_builder.build_late_goals_no_round(league_query, rounds)
                await update.message.reply_text(text, parse_mode="Markdown")
                return

            # Get all fixtures for the round
            fixtures = await football_api.get_fixtures_by_round(league_id, season, round_number)
            if not fixtures:
                await update.message.reply_text(
                    f"❌ No encontré partidos para la jornada *{round_number}* de *{league_query}*.\n"
                    f"Puede que esa jornada no exista o aún no se haya jugado.",
                    parse_mode="Markdown"
                )
                return

            # For each finished/live fixture, get events and filter 90+ goals
            await update.message.reply_text(
                f"⏳ Analizando {len(fixtures)} partido(s) de la jornada {round_number}..."
            )
            results = []
            for f in fixtures:
                status_short = f["fixture"]["status"]["short"]
                # Only analyze finished or live matches
                if status_short not in ("FT", "AET", "PEN", "1H", "2H", "HT", "ET", "P", "LIVE"):
                    results.append({
                        "fixture": f["fixture"],
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
                    # 90+ means elapsed >= 90 with extra time, OR extra is set
                    if (minute >= 90 and extra) or (minute > 90):
                        late_goals.append({
                            "minute": minute,
                            "extra": extra,
                            "scorer": ev.get("player", {}).get("name", "?"),
                            "team": ev.get("team", {}).get("name", "?"),
                            "type": ev.get("detail", ""),
                        })

                status_label = _status_label(status_short, f["fixture"]["status"].get("elapsed"))
                results.append({
                    "fixture": f["fixture"],
                    "home": f["teams"]["home"]["name"],
                    "away": f["teams"]["away"]["name"],
                    "score_home": f.get("goals", {}).get("home", 0),
                    "score_away": f.get("goals", {}).get("away", 0),
                    "status": status_label,
                    "late_goals": late_goals,
                })

            text = response_builder.build_late_goals(results, league_query, round_number)

        elif intent["type"] == "live_fixtures":
            fixtures = await football_api.get_live_fixtures(
                min_minute=intent.get("min_minute")
            )
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
                text = f"❌ No encontré un partido en vivo con esos equipos."

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
                # Try today's fixtures
                today_fixtures = await football_api.get_today_fixtures()
                fixture = _find_fixture(today_fixtures, team1, team2)
            if fixture:
                fixture_id = fixture["fixture"]["id"]
                stats = await football_api.get_fixture_stats(fixture_id)
                events = await football_api.get_fixture_events(fixture_id)
                text = response_builder.build_fixture_stats(fixture, stats, events)
            else:
                text = f"❌ No encontré el partido solicitado."

        else:
            text = (
                "No entendí tu consulta. Puedes preguntarme:\n\n"
                "• `¿Qué partidos están en vivo?`\n"
                "• `¿Partidos en minuto 80+?`\n"
                "• `¿Cómo va la Premier League?`\n"
                "• `Tabla de La Liga`\n"
                "• `Goleadores Champions League`\n"
                "• `Estadísticas Chelsea vs Arsenal`\n\n"
                "O usa /help para ver todos los comandos."
            )

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text("❌ Ocurrió un error al procesar tu consulta. Intenta de nuevo.")


def _find_fixture(fixtures: list, team1: str, team2: str) -> dict | None:
    """Find a fixture by team names (fuzzy match)."""
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
