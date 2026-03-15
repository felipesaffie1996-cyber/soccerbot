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
El usuario envía mensajes en español sobre fútbol. Devuelve SOLO un JSON válido, sin texto adicional.

Intenciones posibles:

- live_fixtures: partidos en vivo. Opcional: min_minute (int).
- today_fixtures: partidos de hoy. Opcional: league (string).
- standings: tabla de posiciones. Requiere: league (string).
- top_scorers: goleadores. Requiere: league (string).
- live_fixture_detail: detalle de partido en vivo. Requiere: team1, team2.
- fixture_stats: estadísticas de partido. Requiere: team1, team2.
- late_goals_multi: goles en 90+ por jornada(s) y liga(s).
  Requiere: leagues (array), rounds (array de ints) o rounds_count (int si dice "últimas N").
- team_results: últimos resultados de un equipo. Requiere: team (string). Opcional: n (int, default 10).
- team_next: próximos partidos de un equipo. Requiere: team (string). Opcional: n (int, default 5).
- league_next: próximos partidos de una liga. Requiere: league (string). Opcional: n (int, default 10).
- head_to_head: historial entre dos equipos. Requiere: team1, team2. Opcional: n (int, default 10).
- round_goals: total goles, BTTS y desglose 1T/2T de una o varias jornadas.
  Requiere: league (string), rounds (array de ints) o rounds_count (int).
- unknown: no se entiende.

Ejemplos:
"últimos 5 partidos de la Juventus" → {"type": "team_results", "team": "Juventus", "n": 5}
"cuándo juega el Real Madrid" → {"type": "team_next", "team": "Real Madrid", "n": 5}
"historial Manchester City vs Liverpool" → {"type": "head_to_head", "team1": "Manchester City", "team2": "Liverpool"}
"cuántos goles hubo en la jornada 5 de la premier" → {"type": "round_goals", "league": "Premier League", "rounds": [5]}
"goles y btts últimas 4 jornadas bundesliga" → {"type": "round_goals", "league": "Bundesliga", "rounds_count": 4}
"goles en el primer tiempo jornada 30 premier league" → {"type": "round_goals", "league": "Premier League", "rounds": [30]}
"máximo goles en 1T jornada 30 premier" → {"type": "round_goals", "league": "Premier League", "rounds": [30]}
"goles sobre el final jornada 7 chile" → {"type": "late_goals_multi", "leagues": ["Primera Division Chile"], "rounds": [7]}
"últimas 3 fechas de goles al final en chile y holanda" → {"type": "late_goals_multi", "leagues": ["Primera Division Chile", "Eredivisie"], "rounds": null, "rounds_count": 3}
"tabla de la premier" → {"type": "standings", "league": "Premier League"}
"partidos en vivo" → {"type": "live_fixtures"}
"próximos partidos de la Champions" → {"type": "league_next", "league": "Champions League"}

Devuelve SOLO el JSON."""


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
        logger.error(f"Claude intent parsing failed: {e}")
        return intent_parser.parse(text)


async def get_last_n_rounds(league_query: str, n: int) -> list[int]:
    import re
    league_id, season = await football_api.find_league(league_query)
    if not league_id:
        return []
    available = await football_api.get_available_rounds(league_id, season)
    numbered = sorted(set(
        int(m.group(1)) for r in available
        if (m := re.search(r'(\d+)$', r.strip()))
    ))
    return numbered[-n:] if len(numbered) >= n else numbered


async def process_late_goals_single(league_query: str, round_number: int) -> str:
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
        events = await football_api.get_fixture_events(f["fixture"]["id"])
        late_goals = [
            {
                "minute": ev.get("time", {}).get("elapsed", 0) or 0,
                "extra": ev.get("time", {}).get("extra"),
                "scorer": ev.get("player", {}).get("name", "?"),
                "team": ev.get("team", {}).get("name", "?"),
                "type": ev.get("detail", ""),
            }
            for ev in events
            if ev.get("type") == "Goal" and (ev.get("time", {}).get("elapsed", 0) or 0) >= 90
        ]
        results.append({
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
            "score_home": f.get("goals", {}).get("home", 0),
            "score_away": f.get("goals", {}).get("away", 0),
            "status": _status_label(status_short, f["fixture"]["status"].get("elapsed")),
            "late_goals": late_goals,
        })
    return response_builder.build_late_goals(results, league_query, round_number)


async def handle_late_goals_multi(intent: dict, update: Update):
    leagues = intent.get("leagues", [])
    rounds = intent.get("rounds")
    rounds_count = intent.get("rounds_count")
    if not leagues:
        await update.message.reply_text("Especifica al menos una liga.", parse_mode="Markdown")
        return
    if not rounds and rounds_count:
        await update.message.reply_text(f"⏳ Buscando las últimas {rounds_count} jornadas...")
        rounds = await get_last_n_rounds(leagues[0], rounds_count)
        if not rounds:
            await update.message.reply_text("❌ No pude determinar las últimas jornadas.")
            return
    if not rounds:
        await update.message.reply_text("Especifica las jornadas.")
        return
    await update.message.reply_text(
        f"⏳ Analizando {len(leagues)} liga(s) × {len(rounds)} jornada(s)...\n"
        f"Ligas: {', '.join(leagues)}\nJornadas: {', '.join(str(r) for r in rounds)}"
    )
    tasks = [(league, rnd) for league in leagues for rnd in rounds]
    results = await asyncio.gather(*[process_late_goals_single(l, r) for l, r in tasks], return_exceptions=True)
    for league in leagues:
        for i, (lbl_league, lbl_round) in enumerate(tasks):
            if lbl_league == league:
                msg = results[i] if not isinstance(results[i], Exception) else f"❌ Error jornada {lbl_round}"
                try:
                    await update.message.reply_text(msg, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(msg)


async def handle_round_goals(intent: dict, update: Update):
    import re
    league_query = intent.get("league", "")
    rounds = intent.get("rounds")
    rounds_count = intent.get("rounds_count")
    if not league_query:
        await update.message.reply_text("Especifica una liga.")
        return
    league_id, season = await football_api.find_league(league_query)
    if not league_id:
        await update.message.reply_text(f"❌ No encontré la liga: *{league_query}*", parse_mode="Markdown")
        return
    if not rounds and rounds_count:
        await update.message.reply_text(f"⏳ Buscando las últimas {rounds_count} jornadas de {league_query}...")
        available = await football_api.get_available_rounds(league_id, season)
        numbered = sorted(set(
            int(m.group(1)) for r in available
            if (m := re.search(r'(\d+)$', r.strip()))
        ))
        rounds = numbered[-rounds_count:] if len(numbered) >= rounds_count else numbered
    if not rounds:
        await update.message.reply_text("Especifica las jornadas.")
        return
    await update.message.reply_text(f"⏳ Calculando goles, BTTS y desglose 1T/2T de {len(rounds)} jornada(s)...")
    summaries = await asyncio.gather(*[
        football_api.get_round_goals_summary(league_id, season, r) for r in rounds
    ])
    if len(rounds) == 1:
        text = response_builder.build_round_goals_summary(summaries[0], league_query)
    else:
        text = response_builder.build_multi_round_summary(list(summaries), league_query)
    await update.message.reply_text(text, parse_mode="Markdown")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    welcome = (
        "⚽ *SoccerBot activo*\n\n"
        "Ejemplos de lo que puedo responder:\n\n"
        "• `¿Qué partidos están en vivo?`\n"
        "• `Últimos 5 partidos de la Juventus`\n"
        "• `¿Cuándo juega el Real Madrid?`\n"
        "• `Historial Manchester City vs Liverpool`\n"
        "• `Tabla de la Premier League`\n"
        "• `Goleadores Champions League`\n"
        "• `Goles y BTTS últimas 4 jornadas Bundesliga`\n"
        "• `Goles en el primer tiempo jornada 30 Premier`\n"
        "• `Goles sobre el final jornada 7 Primera División Chile`\n"
        "• `Próximos partidos de la Champions`\n\n"
        "Datos en vivo de API-Football ✅"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    help_text = (
        "📖 *Comandos:*\n\n"
        "/start — Bienvenida\n"
        "/live — Partidos en vivo\n"
        "/today — Partidos de hoy\n"
        "/standings [liga] — Tabla\n"
        "/top [liga] — Goleadores\n"
        "/help — Ayuda\n\n"
        "O escribe en lenguaje natural cualquier consulta de fútbol 👇"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def live_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    await update.message.reply_text("⏳ Consultando partidos en vivo...")
    try:
        fixtures = await football_api.get_live_fixtures()
        await update.message.reply_text(response_builder.build_live_fixtures(fixtures), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /live: {e}")
        await update.message.reply_text("❌ Error al consultar la API.")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    await update.message.reply_text("⏳ Consultando partidos de hoy...")
    try:
        fixtures = await football_api.get_today_fixtures()
        await update.message.reply_text(response_builder.build_today_fixtures(fixtures), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /today: {e}")
        await update.message.reply_text("❌ Error al consultar la API.")


async def standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    league_query = " ".join(context.args) if context.args else None
    if not league_query:
        await update.message.reply_text("Ejemplo: `/standings Premier League`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"⏳ Buscando tabla de {league_query}...")
    try:
        league_id, season = await football_api.find_league(league_query)
        if not league_id:
            await update.message.reply_text(f"❌ No encontré: *{league_query}*", parse_mode="Markdown")
            return
        standings = await football_api.get_standings(league_id, season)
        await update.message.reply_text(response_builder.build_standings(standings, league_query), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /standings: {e}")
        await update.message.reply_text("❌ Error al consultar la API.")


async def top_scorers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    league_query = " ".join(context.args) if context.args else None
    if not league_query:
        await update.message.reply_text("Ejemplo: `/top Champions League`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"⏳ Buscando goleadores de {league_query}...")
    try:
        league_id, season = await football_api.find_league(league_query)
        if not league_id:
            await update.message.reply_text(f"❌ No encontré: *{league_query}*", parse_mode="Markdown")
            return
        scorers = await football_api.get_top_scorers(league_id, season)
        await update.message.reply_text(response_builder.build_top_scorers(scorers, league_query), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /top: {e}")
        await update.message.reply_text("❌ Error al consultar la API.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    user_text = update.message.text.strip()
    if not user_text:
        return
    logger.info(f"Message from {chat_id}: {user_text}")
    intent = await parse_intent_with_claude(user_text)
    logger.info(f"Detected intent: {intent}")
    await update.message.reply_text("⏳ Consultando datos...")

    try:
        t = intent["type"]

        if t == "late_goals_multi":
            await handle_late_goals_multi(intent, update)
            return

        elif t == "round_goals":
            await handle_round_goals(intent, update)
            return

        elif t == "live_fixtures":
            fixtures = await football_api.get_live_fixtures(min_minute=intent.get("min_minute"))
            text = response_builder.build_live_fixtures(fixtures, min_minute=intent.get("min_minute"))

        elif t == "live_fixture_detail":
            fixtures = await football_api.get_live_fixtures()
            fixture = _find_fixture(fixtures, intent.get("team1"), intent.get("team2"))
            if fixture:
                fid = fixture["fixture"]["id"]
                stats = await football_api.get_fixture_stats(fid)
                events = await football_api.get_fixture_events(fid)
                lineups = await football_api.get_fixture_lineups(fid)
                text = response_builder.build_fixture_detail(fixture, stats, events, lineups)
            else:
                text = "❌ No encontré ese partido en vivo."

        elif t == "today_fixtures":
            fixtures = await football_api.get_today_fixtures(league_query=intent.get("league"))
            text = response_builder.build_today_fixtures(fixtures, league_filter=intent.get("league"))

        elif t == "standings":
            league_id, season = await football_api.find_league(intent.get("league", ""))
            if not league_id:
                text = f"❌ No encontré la liga: *{intent.get('league')}*"
            else:
                standings = await football_api.get_standings(league_id, season)
                text = response_builder.build_standings(standings, intent.get("league", ""))

        elif t == "top_scorers":
            league_id, season = await football_api.find_league(intent.get("league", ""))
            if not league_id:
                text = f"❌ No encontré la liga: *{intent.get('league')}*"
            else:
                scorers = await football_api.get_top_scorers(league_id, season)
                text = response_builder.build_top_scorers(scorers, intent.get("league", ""))

        elif t == "fixture_stats":
            fixtures = await football_api.get_live_fixtures()
            fixture = _find_fixture(fixtures, intent.get("team1"), intent.get("team2"))
            if not fixture:
                today = await football_api.get_today_fixtures()
                fixture = _find_fixture(today, intent.get("team1"), intent.get("team2"))
            if fixture:
                fid = fixture["fixture"]["id"]
                stats = await football_api.get_fixture_stats(fid)
                events = await football_api.get_fixture_events(fid)
                text = response_builder.build_fixture_stats(fixture, stats, events)
            else:
                text = "❌ No encontré ese partido."

        elif t == "team_results":
            team_name = intent.get("team", "")
            n = intent.get("n", 10)
            team_id = await football_api.find_team(team_name)
            if not team_id:
                text = f"❌ No encontré el equipo: *{team_name}*"
            else:
                fixtures = await football_api.get_team_last_fixtures(team_id, n)
                text = response_builder.build_team_results(fixtures, team_name)

        elif t == "team_next":
            team_name = intent.get("team", "")
            n = intent.get("n", 5)
            team_id = await football_api.find_team(team_name)
            if not team_id:
                text = f"❌ No encontré el equipo: *{team_name}*"
            else:
                fixtures = await football_api.get_team_next_fixtures(team_id, n)
                text = response_builder.build_next_fixtures(fixtures, team_name)

        elif t == "league_next":
            league_query = intent.get("league", "")
            n = intent.get("n", 10)
            league_id, season = await football_api.find_league(league_query)
            if not league_id:
                text = f"❌ No encontré la liga: *{league_query}*"
            else:
                fixtures = await football_api.get_next_fixtures_by_league(league_id, season, n)
                text = response_builder.build_next_fixtures(fixtures, league_query)

        elif t == "head_to_head":
            team1 = intent.get("team1", "")
            team2 = intent.get("team2", "")
            n = intent.get("n", 10)
            t1_id = await football_api.find_team(team1)
            t2_id = await football_api.find_team(team2)
            if not t1_id or not t2_id:
                text = f"❌ No encontré uno de los equipos: *{team1}* / *{team2}*"
            else:
                fixtures = await football_api.get_head_to_head(t1_id, t2_id, n)
                text = response_builder.build_head_to_head(fixtures, team1, team2)

        else:
            text = (
                "No entendí tu consulta. Ejemplos:\n\n"
                "• `Últimos partidos de la Juventus`\n"
                "• `¿Cuándo juega el Barcelona?`\n"
                "• `Historial Real Madrid vs Atletico`\n"
                "• `Goles y BTTS últimas 5 jornadas Premier`\n"
                "• `Goles en el primer tiempo jornada 30 Premier`\n"
                "• `Goles sobre el final jornada 7 Chile`\n"
                "• `Tabla de La Liga`\n"
            )

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text("❌ Ocurrió un error. Intenta de nuevo.")


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
