import aiohttp
import logging
import re
from datetime import datetime, timezone
from typing import Optional
import difflib

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

LEAGUE_ALIASES = {
    "premier league": 39, "epl": 39, "premier": 39,
    "championship": 40,
    "fa cup": 45,
    "league cup": 46, "carabao cup": 46,
    "la liga": 140, "laliga": 140, "primera division": 140,
    "copa del rey": 143,
    "bundesliga": 78, "bundesliga 1": 78,
    "dfb-pokal": 81,
    "serie a": 135, "calcio": 135,
    "coppa italia": 137,
    "ligue 1": 61, "ligue1": 61,
    "coupe de france": 66,
    "primeira liga": 94, "liga nos": 94,
    "eredivisie": 88,
    "champions league": 2, "ucl": 2, "champions": 2,
    "europa league": 3, "uel": 3, "europa": 3,
    "conference league": 848, "uecl": 848,
    "copa libertadores": 13, "libertadores": 13,
    "copa sudamericana": 11, "sudamericana": 11,
    "mls": 253,
    "liga profesional": 128, "primera division argentina": 128,
    "primera division chile": 265, "primera chile": 265,
    "primera division de chile": 265, "primera div chile": 265,
    "brasileirao": 71, "serie a brasil": 71,
    "liga mx": 262,
    "world cup": 1,
    "euro": 4, "euros": 4,
    "copa america": 9,
    "nations league": 5,
}

CALENDAR_YEAR_LEAGUES = {265, 128, 71, 262, 253, 11, 13, 9}

CURRENT_SEASON = datetime.now().year
if datetime.now().month < 7:
    CURRENT_SEASON = datetime.now().year - 1

CURRENT_CALENDAR_SEASON = datetime.now().year


def get_season_for_league(league_id: int) -> int:
    if league_id in CALENDAR_YEAR_LEAGUES:
        return CURRENT_CALENDAR_SEASON
    return CURRENT_SEASON


class FootballAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"x-apisports-key": api_key}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        session = await self._get_session()
        url = f"{BASE_URL}/{endpoint}"
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"API error {resp.status} for {url}")
                    return {"response": [], "errors": [f"HTTP {resp.status}"]}
                data = await resp.json()
                remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
                logger.info(f"API call: {endpoint} | Remaining quota: {remaining}")
                return data
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error: {e}")
            return {"response": [], "errors": [str(e)]}

    async def get_live_fixtures(self, min_minute: int = None) -> list:
        data = await self._get("fixtures", {"live": "all"})
        fixtures = data.get("response", [])
        if min_minute is not None:
            return [f for f in fixtures
                    if (f.get("fixture", {}).get("status", {}).get("elapsed") or 0) >= min_minute]
        return fixtures

    async def get_today_fixtures(self, league_query: str = None) -> list:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        params = {"date": today}
        if league_query:
            league_id, _ = await self.find_league(league_query)
            if league_id:
                params["league"] = league_id
                params["season"] = get_season_for_league(league_id)
        data = await self._get("fixtures", params)
        return data.get("response", [])

    async def get_fixture_stats(self, fixture_id: int) -> list:
        data = await self._get("fixtures/statistics", {"fixture": fixture_id})
        return data.get("response", [])

    async def get_fixture_events(self, fixture_id: int) -> list:
        data = await self._get("fixtures/events", {"fixture": fixture_id})
        return data.get("response", [])

    async def get_fixture_lineups(self, fixture_id: int) -> list:
        data = await self._get("fixtures/lineups", {"fixture": fixture_id})
        return data.get("response", [])

    async def find_league(self, query: str) -> tuple[Optional[int], int]:
        q = query.lower().strip()
        if q in LEAGUE_ALIASES:
            league_id = LEAGUE_ALIASES[q]
            return league_id, get_season_for_league(league_id)
        best = difflib.get_close_matches(q, LEAGUE_ALIASES.keys(), n=1, cutoff=0.6)
        if best:
            league_id = LEAGUE_ALIASES[best[0]]
            return league_id, get_season_for_league(league_id)
        data = await self._get("leagues", {"search": query})
        leagues = data.get("response", [])
        if leagues:
            for entry in leagues:
                league_id = entry["league"]["id"]
                season = get_season_for_league(league_id)
                for s in entry.get("seasons", []):
                    if s.get("current") and s.get("year") == season:
                        return league_id, season
            league_id = leagues[0]["league"]["id"]
            return league_id, get_season_for_league(league_id)
        return None, CURRENT_SEASON

    async def find_team(self, query: str, league_id: int = None) -> Optional[int]:
        params = {"search": query}
        if league_id:
            params["league"] = league_id
        data = await self._get("teams", params)
        teams = data.get("response", [])
        if teams:
            return teams[0]["team"]["id"]
        return None

    async def get_team_last_fixtures(self, team_id: int, n: int = 10) -> list:
        data = await self._get("fixtures", {"team": team_id, "last": n})
        return data.get("response", [])

    async def get_team_next_fixtures(self, team_id: int, n: int = 5) -> list:
        data = await self._get("fixtures", {"team": team_id, "next": n})
        return data.get("response", [])

    async def get_next_fixtures_by_league(self, league_id: int, season: int, n: int = 10) -> list:
        data = await self._get("fixtures", {"league": league_id, "season": season, "next": n})
        return data.get("response", [])

    async def get_head_to_head(self, team1_id: int, team2_id: int, last: int = 10) -> list:
        data = await self._get("fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}",
            "last": last,
        })
        return data.get("response", [])

    async def get_standings(self, league_id: int, season: int) -> list:
        data = await self._get("standings", {"league": league_id, "season": season})
        response = data.get("response", [])
        if response:
            return response[0].get("league", {}).get("standings", [])
        return []

    async def get_top_scorers(self, league_id: int, season: int) -> list:
        data = await self._get("players/topscorers", {"league": league_id, "season": season})
        return data.get("response", [])

    async def get_fixtures_by_round(self, league_id: int, season: int, round_number: int) -> list:
        if league_id in CALENDAR_YEAR_LEAGUES:
            season = CURRENT_CALENDAR_SEASON
        available_rounds = await self.get_available_rounds(league_id, season)
        logger.info(f"Available rounds for league {league_id} season {season}: {available_rounds}")
        target = None
        for r in available_rounds:
            if re.search(rf'[-\s]{round_number}$', r.strip()):
                target = r
                break
        if target:
            data = await self._get("fixtures", {"league": league_id, "season": season, "round": target})
            fixtures = data.get("response", [])
            if fixtures:
                return fixtures
        for round_str in [
            f"Regular Season - {round_number}",
            f"Clausura - {round_number}",
            f"Apertura - {round_number}",
            f"Liga - {round_number}",
            f"Fecha {round_number}",
            f"Round {round_number}",
            f"Week {round_number}",
            f"Matchday {round_number}",
        ]:
            data = await self._get("fixtures", {"league": league_id, "season": season, "round": round_str})
            fixtures = data.get("response", [])
            if fixtures:
                return fixtures
        return []

    async def get_available_rounds(self, league_id: int, season: int) -> list:
        if league_id in CALENDAR_YEAR_LEAGUES:
            season = CURRENT_CALENDAR_SEASON
        data = await self._get("fixtures/rounds", {"league": league_id, "season": season})
        return data.get("response", [])

    async def get_round_goals_summary(self, league_id: int, season: int, round_number: int) -> dict:
        fixtures = await self.get_fixtures_by_round(league_id, season, round_number)
        total_goals = 0
        first_half_goals = 0
        second_half_goals = 0
        btts = 0
        played = 0
        matches = []
        for f in fixtures:
            status = f["fixture"]["status"]["short"]
            if status not in ("FT", "AET", "PEN"):
                continue
            played += 1
            h = f.get("goals", {}).get("home", 0) or 0
            a = f.get("goals", {}).get("away", 0) or 0
            total_goals += h + a
            if h > 0 and a > 0:
                btts += 1
            events = await self.get_fixture_events(f["fixture"]["id"])
            fh = sum(1 for ev in events
                     if ev.get("type") == "Goal"
                     and (ev.get("time", {}).get("elapsed", 0) or 0) <= 45
                     and not ev.get("time", {}).get("extra"))
            sh = (h + a) - fh
            first_half_goals += fh
            second_half_goals += sh
            matches.append({
                "home": f["teams"]["home"]["name"],
                "away": f["teams"]["away"]["name"],
                "score_h": h,
                "score_a": a,
                "btts": h > 0 and a > 0,
                "first_half_goals": fh,
                "second_half_goals": sh,
            })
        return {
            "round": round_number,
            "played": played,
            "total_goals": total_goals,
            "first_half_goals": first_half_goals,
            "second_half_goals": second_half_goals,
            "avg_goals": round(total_goals / played, 2) if played else 0,
            "btts": btts,
            "btts_pct": round(btts / played * 100) if played else 0,
            "matches": matches,
        }

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
