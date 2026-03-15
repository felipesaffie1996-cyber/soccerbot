import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000

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
    score = f"{h_goals} - {a_goals}" if h_goals is not None and a_goals is not None else "vs"
    return f"*{home}* {score} *{away}* | {_status_label(short, elapsed)}"


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
        by_league: dict[str, list] = {}
        for f in fixtures:
            league_name = f.get("league", {}).get("name", "Desconocida")
            country = f.get("league", {}).get("country", "")
            key = f"{league_name} ({country})" if country else league_name
            by_league.setdefault(key, []).append(f)
        header = f"📅 *Partidos de hoy* — {len(fixtures)} en {len(by_league)} competición(es)\n\n"
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
                    lines.append(f"  • {home} {h_g}-{a_g} {away} | {_status_label(short, elapsed)}")
                else:
                    ts = f["fixture"].get("timestamp")
                    time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M UTC") if ts else "?"
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
        league = fixture.get("league", {})
        lines = [
            f"⚽ *{home} {h_g} - {a_g} {away}*",
            f"🏆 {league.get('name', '')} | {_status_label(status.get('short', ''), status.get('elapsed'))}",
            "",
        ]
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
        if stats:
            lines.append("📊 *Estadísticas:*")
            home_stats = {s["type"]: s["value"] for s in stats[0].get("statistics", [])} if stats else {}
            away_stats = {s["type"]: s["value"] for s in stats[1].get("statistics", [])} if len(stats) > 1 else {}
            for stat_name in ["Ball Possession", "Total Shots", "Shots on Goal", "Fouls",
                              "Corner Kicks", "Offsides", "Yellow Cards", "Red Cards",
                              "Goalkeeper Saves", "Total passes"]:
                h_val = home_stats.get(stat_name, "-")
                a_val = away_stats.get(stat_name, "-")
                if h_val != "-" or a_val != "-":
                    lines.append(f"  {stat_name}: *{h_val}* — *{a_val}*")
            lines.append("")
        if lineups:
            lines.append("👥 *Alineaciones:*")
            for lineup in lineups:
                t_name = lineup.get("team", {}).get("name", "")
                formation = lineup.get("formation", "")
                players = [p["player"]["name"] for p in lineup.get("startXI", []) if p.get("player")]
                lines.append(f"  *{t_name}* ({formation}): {', '.join(players)}")
            lines.append("")
        return _truncate("\n".join(lines))

    def build_fixture_stats(self, fixture: dict, stats: list, events: list) -> str:
        return self.build_fixture_detail(fixture, stats, events, lineups=[])

    def build_standings(self, standings: list, league_name: str) -> str:
        if not standings:
            return f"❌ No se encontraron standings para *{league_name}*."
        groups = standings if isinstance(standings[0], list) else [standings]
        lines = [f"📊 *Tabla — {league_name}*\n"]
        for group in groups:
            if not group:
                continue
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
                lines.append(f"`{str(pos).rjust(2)}   {team[:20].ljust(20)}  {str(pts).rjust(3)}   {str(played).rjust(2)}  {gd_str.rjust(4)}`")
            lines.append("")
        lines.append("_G=Ganados D=Empates P=Perdidos_")
        return _truncate("\n".join(lines))

    def build_top_scorers(self, scorers: list, league_name: str) -> str:
        if not scorers:
            return f"❌ No se encontraron goleadores para *{league_name}*."
        lines = [f"⚽ *Goleadores — {league_name}*\n"]
        lines.append("`Pos  Jugador              Club              Goles  Asist`")
        for i, entry in enumerate(scorers[:15], 1):
            player = entry.get("player", {})
            stat = entry.get("statistics", [{}])[0]
            name = player.get("name", "?")[:20].ljust(20)
            club = stat.get("team", {}).get("name", "?")[:16].ljust(16)
            goals = stat.get("goals", {}).get("total", 0) or 0
            assists = stat.get("goals", {}).get("assists", 0) or 0
            lines.append(f"`{str(i).rjust(2)}   {name}  {club}  {str(goals).rjust(5)}  {str(assists).rjust(5)}`")
        return _truncate("\n".join(lines))

    def build_late_goals(self, results: list, league_name: str, round_number: int) -> str:
        if not results:
            return f"❌ No encontré partidos para la *Jornada {round_number}* de *{league_name}*."
        total_late = sum(len(r["late_goals"]) for r in results)
        matches_with = sum(1 for r in results if r["late_goals"])
        lines = [f"⏱ *Goles en tiempo adicional (90+)*", f"🏆 {league_name} — Jornada {round_number}\n"]
        for item in results:
            match_line = f"*{item['home']} {item['score_home']}-{item['score_away']} {item['away']}* ({item['status']})"
            if item["late_goals"]:
                lines.append(f"⚽ {match_line}")
                for g in item["late_goals"]:
                    min_str = f"90+{g['extra']}'" if g.get("extra") else f"{g['minute']}'"
                    type_str = " 🎯 (pen)" if "Penalty" in g.get("type", "") else ""
                    lines.append(f"    ⚽ {min_str} {g['scorer']} ({g['team']}){type_str}")
            else:
                lines.append(f"➖ {match_line} — sin goles en 90+")
        lines.append("")
        lines.append(f"📊 *Resumen:* {total_late} gol(es) en 90+ en {matches_with} de {len(results)} partido(s)")
        return _truncate("\n".join(lines))

    def build_late_goals_no_round(self, league_name: str, available_rounds: list) -> str:
        lines = [f"¿De qué jornada quieres los goles en tiempo adicional de *{league_name}*?\n"]
        if available_rounds:
            recent = available_rounds[-5:] if len(available_rounds) >= 5 else available_rounds
            lines.append("Últimas jornadas disponibles:")
            for r in reversed(recent):
                lines.append(f"  • {r}")
            lines.append("\nEjemplo: `goles sobre el final jornada 7 Primera División Chile`")
        return "\n".join(lines)

    def build_team_results(self, fixtures: list, team_name: str) -> str:
        if not fixtures:
            return f"❌ No encontré resultados para *{team_name}*."
        lines = [f"📋 *Últimos resultados — {team_name}*\n"]
        wins = draws = losses = goals_for = goals_against = 0
        last_loss_date = None
        for f in reversed(fixtures):
            status = f["fixture"]["status"]["short"]
            if status not in ("FT", "AET", "PEN"):
                continue
            home_team = f["teams"]["home"]["name"]
            away_team = f["teams"]["away"]["name"]
            h_g = f.get("goals", {}).get("home", 0) or 0
            a_g = f.get("goals", {}).get("away", 0) or 0
            is_home = team_name.lower() in home_team.lower()
            my_goals = h_g if is_home else a_g
            opp_goals = a_g if is_home else h_g
            opp_name = away_team if is_home else home_team
            goals_for += my_goals
            goals_against += opp_goals
            date = f["fixture"].get("date", "")[:10]
            league = f.get("league", {}).get("name", "")
            if my_goals > opp_goals:
                result = "✅ V"
                wins += 1
            elif my_goals == opp_goals:
                result = "➖ E"
                draws += 1
            else:
                result = "❌ D"
                losses += 1
                last_loss_date = date
            venue = "🏠" if is_home else "✈️"
            lines.append(f"{venue} {result} {my_goals}-{opp_goals} vs *{opp_name}* | {date} | _{league}_")
        total = wins + draws + losses
        lines.append("")
        lines.append(f"📊 *Resumen ({total} partidos):* {wins}V {draws}E {losses}D")
        lines.append(f"⚽ Goles: {goals_for} a favor, {goals_against} en contra")
        if last_loss_date:
            lines.append(f"📅 Última derrota: {last_loss_date}")
        else:
            lines.append(f"🔥 ¡Sin derrotas en los últimos {total} partidos!")
        return _truncate("\n".join(lines))

    def build_next_fixtures(self, fixtures: list, team_or_league: str) -> str:
        if not fixtures:
            return f"❌ No encontré próximos partidos para *{team_or_league}*."
        lines = [f"📅 *Próximos partidos — {team_or_league}*\n"]
        for f in fixtures:
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            ts = f["fixture"].get("timestamp")
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m %H:%M UTC") if ts else "?"
            league = f.get("league", {}).get("name", "")
            round_info = f.get("league", {}).get("round", "")
            lines.append(f"• *{home}* vs *{away}*")
            lines.append(f"  📅 {date_str} | 🏆 {league} | {round_info}")
            lines.append("")
        return _truncate("\n".join(lines))

    def build_head_to_head(self, fixtures: list, team1: str, team2: str) -> str:
        if not fixtures:
            return f"❌ No encontré historial entre *{team1}* y *{team2}*."
        lines = [f"⚔️ *Head to Head — {team1} vs {team2}*\n"]
        t1_wins = t2_wins = draws = 0
        for f in fixtures:
            status = f["fixture"]["status"]["short"]
            if status not in ("FT", "AET", "PEN"):
                continue
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            h_g = f.get("goals", {}).get("home", 0) or 0
            a_g = f.get("goals", {}).get("away", 0) or 0
            date = f["fixture"].get("date", "")[:10]
            league = f.get("league", {}).get("name", "")
            if h_g > a_g:
                result = f"✅ {home}"
                if team1.lower() in home.lower():
                    t1_wins += 1
                else:
                    t2_wins += 1
            elif h_g < a_g:
                result = f"✅ {away}"
                if team1.lower() in away.lower():
                    t1_wins += 1
                else:
                    t2_wins += 1
            else:
                result = "➖ Empate"
                draws += 1
            lines.append(f"• *{home}* {h_g}-{a_g} *{away}* | {result}")
            lines.append(f"  📅 {date} | _{league}_")
            lines.append("")
        lines.append(f"📊 *Balance:* {team1}: {t1_wins}V | Empates: {draws} | {team2}: {t2_wins}V")
        return _truncate("\n".join(lines))

    def build_round_goals_summary(self, summary: dict, league_name: str) -> str:
        if not summary or summary.get("played", 0) == 0:
            return f"❌ No hay datos de goles para esa jornada de *{league_name}*."
        r = summary["round"]
        played = summary["played"]
        total = summary["total_goals"]
        avg = summary["avg_goals"]
        btts = summary["btts"]
        btts_pct = summary["btts_pct"]
        fh = summary.get("first_half_goals", 0)
        sh = summary.get("second_half_goals", 0)
        lines = [
            f"📊 *Resumen de goles — {league_name} Jornada {r}*\n",
            f"✅ Partidos jugados: {played}",
            f"⚽ Total goles: {total} (avg {avg})",
            f"1️⃣ Primer tiempo: {fh} goles",
            f"2️⃣ Segundo tiempo: {sh} goles",
            f"🎯 BTTS: {btts}/{played} ({btts_pct}%)",
            "",
            "*Desglose por partido:*",
        ]
        max_fh = max((m["first_half_goals"] for m in summary["matches"]), default=0)
        for m in summary["matches"]:
            btts_icon = "✅" if m["btts"] else "❌"
            star = " ⭐" if m["first_half_goals"] == max_fh and max_fh > 0 else ""
            lines.append(
                f"  {btts_icon} *{m['home']}* {m['score_h']}-{m['score_a']} *{m['away']}* "
                f"| 1T: {m['first_half_goals']}⚽ 2T: {m['second_half_goals']}⚽{star}"
            )
        lines.append("")
        lines.append(f"⭐ = máximo goles en 1T ({max_fh})")
        return _truncate("\n".join(lines))

    def build_multi_round_summary(self, summaries: list, league_name: str) -> str:
        if not summaries:
            return f"❌ No hay datos para *{league_name}*."
        lines = [f"📊 *Resumen histórico — {league_name}*\n"]
        lines.append("`Jorn  PJ  Goles  1T   2T   Avg  BTTS%`")
        total_goals = total_played = total_btts = total_fh = total_sh = 0
        for s in summaries:
            if s.get("played", 0) == 0:
                continue
            total_goals += s["total_goals"]
            total_played += s["played"]
            total_btts += s["btts"]
            total_fh += s.get("first_half_goals", 0)
            total_sh += s.get("second_half_goals", 0)
            lines.append(
                f"`{str(s['round']).rjust(4)}  "
                f"{str(s['played']).rjust(2)}  "
                f"{str(s['total_goals']).rjust(5)}  "
                f"{str(s.get('first_half_goals', 0)).rjust(3)}  "
                f"{str(s.get('second_half_goals', 0)).rjust(3)}  "
                f"{str(s['avg_goals']).rjust(4)}  "
                f"{str(s['btts_pct']).rjust(4)}%`"
            )
        if total_played > 0:
            overall_avg = round(total_goals / total_played, 2)
            overall_btts = round(total_btts / total_played * 100)
            lines.append("")
            lines.append(f"*Total:* {total_goals} goles en {total_played} partidos")
            lines.append(f"*1T:* {total_fh} goles | *2T:* {total_sh} goles")
            lines.append(f"*Promedio global:* {overall_avg} goles/partido")
            lines.append(f"*BTTS global:* {overall_btts}%")
        return _truncate("\n".join(lines))
