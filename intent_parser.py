import re
import logging

logger = logging.getLogger(__name__)

LATE_GOALS_KEYWORDS = [
    "goles sobre el final", "goles en tiempo adicional", "goles en el 90",
    "goles en tiempo extra", "goles al final", "cuántos goles sobre el final",
    "cuantos goles sobre el final", "goles después del 90", "goles despues del 90",
    "goles en adición", "goles de tiempo adicionado", "goles en el descuento",
    "goles en added time", "goles injury time", "goles en el alargue",
    "goles en tiempo de descuento", "goles tardíos", "goles tardios",
]

ROUND_PATTERN = re.compile(
    r"(?:jornada|ronda|fecha|round|jornada n[uú]mero|fecha n[uú]mero)\s*(\d+)",
    re.IGNORECASE
)

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
    "cómo va el p
