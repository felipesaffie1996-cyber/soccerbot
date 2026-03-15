import re
import logging

logger = logging.getLogger(__name__)

# Keyword patterns
LIVE_KEYWORDS = [
    "en vivo", "en directo", "live", "ahora", "jugando", "jugándose",
    "en curso", "activo", "están jugando", "partido vivo", "partidos vivos"
]

TODAY_KEYWORDS = [
    "hoy", "today", "del día", "esta jornada", "partidos de hoy",
    "qué hay hoy", "que hay hoy", "programados"
]

STANDINGS_KEYWORDS = [
    "tabla", "clasificación", "clasificacion", "posiciones", "standings",
    "clasificatoria", "como va la", "cómo va la", "cómo está la", "como esta la",
    "lider", "líder", "primero", "últimos", "ultimos", "puntos"
]

TOP_SCORERS_KEYWORDS = [
    "goleadores", "máximo goleador", "maximo goleador", "quien mete más",
    "quien mete mas", "artillero", "top scorers", "más goles", "mas goles",
    "quién lidera en goles", "quien lidera en goles"
]

STATS_KEYWORDS = [
    "estadísticas", "estadisticas", "stats", "datos del partido",
    "cómo va el partido", "como va el partido", "resultado", "marcador",
    "goles del partido", "minuto a minuto"
]

MINUTE_PATTERN = re.compile(r"(?:min(?:uto)?\.?\s*|en el\s*)(\d+)(?:\s*\+|más|mas)?", re.IGNORECASE)
MIN_PLUS_PATTERN = re.compile(r"(?:min(?:uto)?\.?\s*|minuto\s*)(\d+)\s*(?:\+|más|mas|o más|o mas|en adelante)", re.IGNORECASE)

# League name extraction patterns
LEAGUE_AFTER_PATTERNS = [
    r"(?:tabla|clasificaci[oó]n|posiciones|standings)\s+(?:de(?:\s+la?)?|del?|en)\s+(.+?)(?:\?|$|\.|,)",
    r"(?:goleadores|artilleros)\s+(?:de(?:\s+la?)?|del?|en)\s+(.+?)(?:\?|$|\.|,)",
    r"(?:c[oó]mo\s+(?:va|est[aá])\s+(?:la?|el?)\s+)(.+?)(?:\?|$|\.|,)",
    r"(?:partidos?\s+de\s+(?:la?\s+)?)(.+?)(?:\?|$|\.|,|\s+hoy|\s+ahora)",
]

# Team name extraction for match queries
MATCH_VS_PATTERN = re.compile(
    r"(?:partido|juego|match)?\s*(.+?)\s+(?:vs?\.?|contra|versus)\s+(.+?)(?:\?|$|\.|,)",
    re.IGNORECASE
)
MATCH_DETAIL_PATTERN = re.compile(
    r"(?:c[oó]mo\s+va\s+(?:el\s+)?|resultado\s+(?:del?\s+)?)(.+?)\s+(?:vs?\.?|contra|versus)\s+(.+?)(?:\?|$|\.|,)",
    re.IGNORECASE
)


class IntentParser:
    def parse(self, text: str) -> dict:
        text_lower = text.lower().strip()

        # --- Minute filter for live matches ---
        min_minute = None
        min_match = MIN_PLUS_PATTERN.search(text_lower)
        if min_match:
            min_minute = int(min_match.group(1))
        else:
            m = MINUTE_PATTERN.search(text_lower)
            if m and any(k in text_lower for k in LIVE_KEYWORDS):
                min_minute = int(m.group(1))

        # --- Match detail / stats: "X vs Y" ---
        vs_match = MATCH_DETAIL_PATTERN.search(text)
        if vs_match:
            return {
                "type": "live_fixture_detail",
                "team1": vs_match.group(1).strip(),
                "team2": vs_match.group(2).strip(),
            }
        vs_basic = MATCH_VS_PATTERN.search(text)
        if vs_basic and any(k in text_lower for k in STATS_KEYWORDS + LIVE_KEYWORDS):
            return {
                "type": "fixture_stats",
                "team1": vs_basic.group(1).strip(),
                "team2": vs_basic.group(2).strip(),
            }

        # --- Top scorers ---
        if any(k in text_lower for k in TOP_SCORERS_KEYWORDS):
            league = self._extract_league(text_lower, "top_scorers")
            return {"type": "top_scorers", "league": league}

        # --- Standings ---
        if any(k in text_lower for k in STANDINGS_KEYWORDS):
            league = self._extract_league(text_lower, "standings")
            return {"type": "standings", "league": league}

        # --- Live fixtures (with optional minute filter) ---
        if any(k in text_lower for k in LIVE_KEYWORDS) or min_minute is not None:
            return {"type": "live_fixtures", "min_minute": min_minute}

        # --- Today's fixtures ---
        if any(k in text_lower for k in TODAY_KEYWORDS):
            league = self._extract_league(text_lower, "today")
            return {"type": "today_fixtures", "league": league}

        # Fallback
        return {"type": "unknown"}

    def _extract_league(self, text: str, context: str) -> str:
        """Try to extract a league name from the query."""
        for pattern in LEAGUE_AFTER_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                league = m.group(1).strip()
                # Remove trailing question marks or punctuation
                league = re.sub(r"[\?\.\!,]+$", "", league).strip()
                if len(league) > 2:
                    return league
        return ""
