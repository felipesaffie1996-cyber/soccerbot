import aiohttp
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
import difflib

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

# Known league mappings (name variations → league_id)
LEAGUE_ALIASES = {
    # England
    "premier league": 39, "epl": 39, "premier": 39,
    "championship": 40,
    "fa cup": 45,
    "league cup": 46, "carabao cup": 46,
    # Spain
    "la liga": 140, "laliga": 140, "primera division": 140,
    "copa del rey": 143,
    # Germany
    "bundesliga": 78, "bundesliga 1": 78,
    "dfb-pokal": 81,
    # Italy
    "serie a": 135, "calcio": 135,
    "coppa italia": 137,
    # France
    "ligue 1": 61, "ligue1": 61,
    "coupe de france": 66,
    # Portugal
    "primeira liga": 94, "liga nos": 94,
    # Netherlands
    "eredivisie": 88,
    # Europe
    "champions league": 2, "ucl": 2, "champions": 2,
    "europa league": 3, "uel": 3, "europa": 3,
    "conference league": 848, "uecl": 848,
    # Americas
    "copa libertadores": 13, "libertadores": 13,
    "copa sudamericana": 11, "sudamericana": 11,
    "mls": 253,
    # Argentina
    "liga profesional": 128, "primera division argentina": 128,
    # Chile
    "primera division chile": 265, "primera chile": 265,
    # Brazil
    "brasileirao": 71, "serie a brasil": 71,
    # Mexico
    "liga mx": 262, "liga mx apertura": 262,
    # World
    "world cup": 1,
    "euro": 4, "euros": 4,
    "copa america": 9,
    "nations league": 5,
}

CURRENT_SEASON = datetime.now().year
# API Football season logic: if before July, use previous year
if datetime.now().month < 7:
    CURRENT_SEASON = datetime.now().year - 1


class FootballAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-apisports-key": api_key,
        }
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
                # Log remaining quota
                remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
                logger.info(f"API call: {endpoint} | Remaining quota: {remaining}")
                return data
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error: {e}")
            return {"response": [], "errors": [str(e)]}

    async def get_live_fixtures(self, min_minute: int = None) -> list:
        """Get all currently live fixtures."""
        data = await self._get("fixtures", {"live": "all"})
        fixtures = data.get("response", [])

        if min_minute is not None:
            filtered = []
            for f in fixtures:
                elapsed = f.get("fixture", {}).get("status", {}).get("elapsed") or 0
                if elapsed >= min_minute:
                    filtered.append(f)
            return filtered

        return fixtures

    async def get_today_fixtures(self, league_query: str = None) -> list:
        """Get all fixtures scheduled for today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        params = {"date": today}

        if league_query:
            league_id, _ = await self.find_league(league_query)
            if league_id:
                params["league"] = league_id
                params["season"] = CURRENT_SEASON

        data = await self._get("fixtures", params)
        return data.get("response", [])

    async def get_fixture_stats(self, fixture_id: int) -> list:
        """Get statistics for a specific fixture."""
        data = await self._get("fixtures/statistics", {"fixture": fixture_id})
        return data.get("response", [])

    async def get_fixture_events(self, fixture_id: int) -> list:
        """Get events (goals, cards, subs) for a fixture."""
        data = await self._get("fixtures/events", {"fixture": fixture_id})
        return data.get("response", [])

    async def get_fixture_lineups(self, fixture_id: int) -> list:
        """Get lineups for a fixture."""
        data = await self._get("fixtures/lineups", {"fixture": fixture_id})
        return data.get("response", [])

    async def find_league(self, query: str) -> tuple[Optional[int], int]:
        """Resolve a league name query to (league_id, season)."""
        q = query.lower().strip()

        # Direct alias match
        if q in LEAGUE_ALIASES:
            return LEAGUE_ALIASES[q], CURRENT_SEASON

        # Fuzzy match against aliases
        best = difflib.get_close_matches(q, LEAGUE_ALIASES.keys(), n=1, cutoff=0.6)
        if best:
            return LEAGUE_ALIASES[best[0]], CURRENT_SEASON

        # Search via API
        data = await self._get("leagues", {"search": query})
        leagues = data.get("response", [])
        if leagues:
            # Prefer currently active leagues
            for entry in leagues:
                seasons = entry.get("seasons", [])
                for s in seasons:
                    if s.get("current") and s.get("year") == CURRENT_SEASON:
                        return entry["league"]["id"], CURRENT_SEASON
            # Fallback to first result
            return leagues[0]["league"]["id"], CURRENT_SEASON

        return None, CURRENT_SEASON

    async def get_standings(self, league_id: int, season: int) -> list:
        """Get standings for a league/season."""
        data = await self._get("standings", {"league": league_id, "season": season})
        response = data.get("response", [])
        if response:
            league_data = response[0].get("league", {})
            return league_data.get("standings", [])
        return []

    async def get_top_scorers(self, league_id: int, season: int) -> list:
        """Get top scorers for a league/season."""
        data = await self._get("players/topscorers", {"league": league_id, "season": season})
        return data.get("response", [])

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
