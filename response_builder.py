import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096; leave margin

STATUS_MAP = {
    "TBD": "🕐 Por confirmar",
    "NS": "🕐 No iniciado",
    "1H": "🟢 1er Tiempo",
    "HT": "⏸ Descanso",
    "2H": "🟢 2do Tiempo",
    "ET": "🟢 Prórroga",
    "BT": "⏸ Descanso ET",
    "P": "🎯 Penales",
    "SUSP": "⚠️ Suspendido",
    "INT": "⚠️ Interrumpido",
    "FT": "✅ Finalizado",
    "AET": "✅ Finalizado (ET)",
    "PEN": "✅ Finalizado (Pen)",
    "PST": "📅 Aplazado",
    "CANC": "❌ Cancelado",
    "ABD": "❌ Abandonado",
    "AWD": "🏆 Resultado administrativo",
    "WO": "🏆 Walkover",
    "LIVE": "🟢 En vivo",
}

EVENT_ICONS = {
    "Goal": "⚽",
    "subst": "🔄",
    "Card": {"yellow": "🟨", "red": "🟥"},
    "Var": "📺",
    "Penalty": "🎯",
}


def _status_label(short: str, elapsed: int = None) -> str:
    label = STATUS_MAP.get(short, short)
    if elapsed and short in ("1H", "2H", "ET", "P", "LIVE"):
        label += f" {elapsed}'"
    return label


def _score_line(fixture: dict) -> str:
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    goals = fixture.get("goals", {})
    h_goals = goals.get("home")
    a_goals = goals.get("away")
    status = fixture["fixture"]["status"]
    short = status.get("short", "")
    elapsed = status.get("elapsed")

    if h_goals is not None and a_goals is not None:
        score = f"{h_goals} - {a_goals}"
    else:
        score = "vs"

    status_str = _status_label(short, elapsed)
    return f"*{home}* {score} *{away}* | {status_str}"


def _truncate(text: str) -> str:
    if len(text) > MAX_MESSAGE_LENGTH:
        return text[:MAX_MESSAGE_LENGTH] + "\n\n_(Mensaje truncado)_"
    return text


class ResponseBuilder:

    def build_live_fixtures(self, fixtures: list, min_minute: int = None) -> str:
        if not fixtures:
            if min_minute:
                return f"⚽ No hay partidos en vivo en el minuto {min_minute}+."
            return "⚽ No hay partidos en vivo en este momento."

        header = f"🟢 *Partidos en vivo{f' (min {min_minute}+)' if min_minute else ''}* — {len(fixtures)} partido(s)\n\n"
        lines = []
        for f in fixtures:
            lines.append(_score_line(f))
            league = f.get("league", {})
            lines.append(f"  🏆 {league.get('name', '')} — {league.get('country', '')}")
            lines.append("")

        return _truncate(header + "\n".join(lines))

    def build_today_fixtures(self, fixtures: list, league_filter: str = None) -> str:
        if not fixtures:
            msg = "📅 No hay partidos programados para hoy"
            if league_filter:
                msg += f" en *{league_filter}*"
            return msg + "."

        # Group by league
        by_league: dict[str, list] = {}
        for f in fixtures:
            league_name = f.get("league", {}).get("name", "Desconocida")
            country = f.get("league", {}).get("country", "")
            key = f"{league_name} ({country})" if country else league_name
            by_league.setdefault(key, []).append(f)

        total = len(fixtures)
        header = f"📅 *Partidos de hoy* — {total} en {len(by_league)} competición(es)\n\n"
        lines = []
        for league_name, matches in sorted(by_league.items()):
            lines.append(f"🏆 *{league_name}*")
            for f in matches:
                home = f["teams"]["home"]["name"]
                away = f["teams"]["away"]["name"]
                status = f["fixture"]["status"]
                short = status.get("short", "NS")
                elapsed = status.get("elapsed")
                goals = f.get("goals", {})
                h_g = goals.get("home")
                a_g = goals.get("away")

                if h_g is not None and a_g is not None and short not in ("NS", "TBD", "PST"):
                    score = f"{h_g}-{a_g}"
                    st = _status_label(short, elapsed)
                    lines.append(f"  • {home} {score} {away} | {st}")
                else:
                    # Get kickoff time
                    ts = f["fixture"].get("timestamp")
                    if ts:
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        time_str = dt.strftime("%H:%M UTC")
                    else:
                        time_str = "?"
                    lines.append(f"  • {home} vs {away} | {time_str}")
            lines.append("")

        return _truncate(header + "\n".join(lines))

    def build_fixture_detail(self, fixture: dict, stats: list, events: list, lineups: list) -> str:
        home = fixture["teams"]["home"]["name"]
        away = fixture["teams"]["away"]["name"]
        goals = fixture.get("goals", {})
        h_g = goals.get("home", 0)
        a_g = goals.get("away", 0)
        status = fixture["fixture"]["status"]
        short = status.get("short", "")
        elapsed = status.get("elapsed")
        league = fixture.get("league", {})

        lines = [
            f"⚽ *{home} {h_g} - {a_g} {away}*",
            f"🏆 {league.get('name', '')} | {_status_label(short, elapsed)}",
            "",
        ]

        # Events (goals, cards, subs)
        if events:
            lines.append("📋 *Eventos:*")
            for ev in events:
                minute = ev.get("time", {}).get("elapsed", "?")
                extra = ev.get("time", {}).get("extra")
                min_str = f"{minute}+{extra}'" if extra else f"{minute}'"
                ev_type = ev.get("type", "")
                detail = ev.get("detail", "")
                player = ev.get("player", {}).get("name", "")
                team = ev.get("team", {}).get("name", "")

                if ev_type == "Goal":
                    icon = "🎯" if "Penalty" in detail else "⚽"
                    lines.append(f"  {icon} {min_str} *{player}* ({team})")
                elif ev_type == "Card":
                    icon = "🟨" if "Yellow" in detail else "🟥"
                    lines.append(f"  {icon} {min_str} {player} ({team})")
                elif ev_type == "subst":
                    assist = ev.get("assist", {}).get("name", "")
                    lines.append(f"  🔄 {min_str} ↑{assist} ↓{player} ({team})")
                elif ev_type == "Var":
                    lines.append(f"  📺 {min_str} VAR: {detail}")
            lines.append("")

        # Stats
        if stats:
            lines.append("📊 *Estadísticas:*")
            home_stats = {s["type"]: s["value"] for s in stats[0].get("statistics", [])} if stats else {}
            away_stats = {s["type"]: s["value"] for s in stats[1].get("statistics", [])} if len(stats) > 1 else {}

            interesting_stats = [
                "Ball Possession", "Total Shots", "Shots on Goal",
                "Fouls", "Corner Kicks", "Offsides", "Yellow Cards",
                "Red Cards", "Goalkeeper Saves", "Total passes",
            ]
            for stat_name in interesting_stats:
                h_val = home_stats.get(stat_name, "-")
                a_val = away_stats.get(stat_name, "-")
                if h_val != "-" or a_val != "-":
                    lines.append(f"  {stat_name}: *{h_val}* — *{a_val}*")
            lines.append("")

        # Lineups
        if lineups:
            lines.append("👥 *Alineaciones:*")
            for lineup in lineups:
                t_name = lineup.get("team", {}).get("name", "")
                formation = lineup.get("formation", "")
                xi = lineup.get("startXI", [])
                players = [p["player"]["name"] for p in xi if p.get("player")]
                lines.append(f"  *{t_name}* ({formation}): {', '.join(players)}")
            lines.append("")

        return _truncate("\n".join(lines))

    def build_fixture_stats(self, fixture: dict, stats: list, events: list) -> str:
        """Shorter stats view for match queries."""
        return self.build_fixture_detail(fixture, stats, events, lineups=[])

    def build_standings(self, standings: list, league_name: str) -> str:
        if not standings:
            return f"❌ No se encontraron standings para *{league_name}*."

        # standings can be a list of groups
        groups = standings if isinstance(standings[0], list) else [standings]
        lines = [f"📊 *Tabla — {league_name}*\n"]

        for group in groups:
            if not group:
                continue
            # Group name (for CL group stage, etc.)
            group_name = group[0].get("group", "")
            if group_name:
                lines.append(f"*{group_name}*")

            lines.append("`Pos  Club                  Pts  PJ   GD`")
            for entry in group:
                pos = entry.get("rank", "?")
                team = entry.get("team", {}).get("name", "?")
                pts = entry.get("points", 0)
                played = entry.get("all", {}).get("played", 0)
                gd = entry.get("goalsDiff", 0)
                gd_str = f"+{gd}" if gd > 0 else str(gd)
                # Truncate long team names
                team_display = team[:20].ljust(20)
                lines.append(f"`{str(pos).rjust(2)}   {team_display}  {str(pts).rjust(3)}   {str(played).rjust(2)}  {gd_str.rjust(4)}`")

            lines.append("")

        # Form key
        lines.append("_G=Ganados D=Empates P=Perdidos_")
        return _truncate("\n".join(lines))

    def build_top_scorers(self, scorers: list, league_name: str) -> str:
        if not scorers:
            return f"❌ No se encontraron goleadores para *{league_name}*."

        lines = [f"⚽ *Goleadores — {league_name}*\n"]
        lines.append("`Pos  Jugador              Club              Goles  Asist`")

        for i, entry in enumerate(scorers[:15], 1):
            player = entry.get("player", {})
            stats_list = entry.get("statistics", [{}])
            stat = stats_list[0] if stats_list else {}

            name = player.get("name", "?")[:20].ljust(20)
            club = stat.get("team", {}).get("name", "?")[:16].ljust(16)
            goals = stat.get("goals", {}).get("total", 0) or 0
            assists = stat.get("goals", {}).get("assists", 0) or 0

            lines.append(f"`{str(i).rjust(2)}   {name}  {club}  {str(goals).rjust(5)}  {str(assists).rjust(5)}`")

        return _truncate("\n".join(lines))
