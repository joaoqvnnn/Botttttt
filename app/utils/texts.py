from datetime import datetime
from zoneinfo import ZoneInfo


TZ = ZoneInfo("America/Sao_Paulo")


def get_greeting() -> str:
    hour = datetime.now(TZ).hour
    if 5 <= hour < 12:
        return "Bom dia"
    elif 12 <= hour < 18:
        return "Boa tarde"
    return "Boa noite"
