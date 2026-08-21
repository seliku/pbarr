# Eine eigene Quelle anbinden

PBArr kennt von Haus aus die deutschsprachigen Mediatheken. Wenn du einen Sender
aus einem anderen Land anbinden willst, schreibst du **eine Datei**. Du musst
nichts registrieren, keine Liste pflegen und keine andere Datei anfassen.

## Die Aufgabe

Eine Quelle beantwortet genau eine Frage:

> Was bietet dieser Sender gerade unter diesem Namen an?

Mehr nicht. Filtern, Qualität wählen, benennen, herunterladen, merken — das
macht der Kern, und zwar für jedes Land gleich.

## Der Vertrag

```python
from app.modules.sources.base import MediathekSource, MediaItem

class MeinSender(MediathekSource):
    name = "meinsender"          # eindeutig, klein geschrieben
    description = "Mediathek von …"
    country = "FR"               # nur zur Information
    version = "1.0.0"

    async def search(self, topic: str) -> list[MediaItem]:
        ...
```

Datei ablegen unter `app/modules/sources/meinsender.py`. Beim nächsten Start
wird sie gefunden.

## MediaItem

```python
MediaItem(
    source="meinsender",         # dein name
    source_id="…",               # stabile Kennung; sonst die Video-URL
    topic="Der Sendungsname",    # wie der Sender die Reihe nennt
    title="Diese Folge",
    description="…",             # optional
    channel="France 2",          # optional
    aired=datetime(…),           # optional, aber sehr empfohlen
    duration_seconds=2700,       # optional
    urls={"hd": "…", "normal": "…", "low": "…"},
    season=None,                 # nur wenn der Sender sie selbst nennt
    episode=None,
)
```

**`urls`** darf beliebige der drei Stufen enthalten. Der Kern fragt nach der
gewünschten und fällt durch die übrigen zurück. Eine einzige Stufe reicht.

**`season` und `episode`** lässt du leer, wenn du sie nicht sicher weisst. Der
Kern liest sie dann aus dem Titel, und wenn dort nichts steht, benennt er nach
dem Sendedatum. **Raten ist schlimmer als weglassen** — eine falsche Nummer
erzeugt eine falsch einsortierte Datei, ein fehlendes Datum nur einen
unscharfen Namen.

**`aired`** solltest du füllen, wenn irgend möglich. Ohne Sendedatum und ohne
Nummer bleibt nur der aktuelle Zeitpunkt, und dann liegen alle Folgen im selben
Jahr.

## Vollständiges Beispiel

```python
"""
Beispielmediathek – zeigt, was eine Quelle zu tun hat.
"""

import logging
from datetime import datetime, timezone
from typing import List

import httpx

from app.modules.sources.base import MediathekSource, MediaItem

logger = logging.getLogger(__name__)


class BeispielSource(MediathekSource):
    name = "beispiel"
    description = "Beispielmediathek"
    country = "XX"
    version = "1.0.0"

    API = "https://api.beispiel.tv/search"

    async def search(self, topic: str) -> List[MediaItem]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(self.API, params={"q": topic})

            if resp.status_code != 200:
                logger.warning(f"{self.name}: HTTP {resp.status_code} fuer '{topic}'")
                return []

            treffer = resp.json().get("results", [])

        except Exception as e:
            # Niemals durchreichen - eine kaputte Quelle darf die anderen
            # nicht mitreissen.
            logger.warning(f"{self.name} nicht erreichbar: {e}")
            return []

        items = []
        for t in treffer:
            urls = {}
            if t.get("hd_url"):
                urls["hd"] = t["hd_url"]
            if t.get("url"):
                urls["normal"] = t["url"]
            if not urls:
                continue

            items.append(MediaItem(
                source=self.name,
                source_id=t.get("id") or urls.get("normal"),
                topic=t.get("series_name", ""),
                title=t.get("title", ""),
                description=t.get("summary"),
                channel=t.get("channel"),
                aired=datetime.fromisoformat(t["aired"]).replace(tzinfo=timezone.utc)
                      if t.get("aired") else None,
                duration_seconds=t.get("duration"),
                urls=urls,
            ))

        logger.info(f"  {self.name}: {len(items)} Treffer fuer '{topic}'")
        return items
```

## Die drei Regeln

**1. Niemals eine Ausnahme durchreichen.** Bei Fehlern eine leere Liste
zurückgeben und selbst protokollieren. Der Kern behandelt eine leere Antwort
als „nichts gefunden oder nicht erreichbar" und **löscht daraufhin nichts**.

Das ist keine Höflichkeit, sondern hart erkauft: Eine frühere Fassung deutete
jede leere Antwort als „Sendung existiert nicht mehr" und räumte die Merkliste
leer, sobald ein Dienst kurz nicht antwortete.

**2. `source_id` muss stabil sein.** Dieselbe Sendung soll bei jeder Abfrage
dieselbe Kennung bekommen — daran erkennt der Kern, was er schon geholt hat.
Hat dein Sender keine stabile Kennung, nimm die Video-URL.

**3. Normalisiere deine Eigenheiten.** Senderbezeichnungen, Qualitätsstufen und
Titelkonventionen unterscheiden sich je Land. Deine Quelle glättet das und gibt
schlichte Daten weiter.

## Ausprobieren

```python
import asyncio
from app.modules.sources.meinsender import MeinSender

async def main():
    q = MeinSender()
    items = await q.search("Irgendeine Sendung")
    print(f"{len(items)} Treffer")
    for i in items[:5]:
        url, qual = i.best_url("hd")
        print(f"{i.aired:%Y-%m-%d}  {i.channel}  {i.title[:40]}  [{qual}]")

asyncio.run(main())
```

Findet der Lader dein Modul, steht es beim Start im Protokoll:

```
✓ Quelle geladen: meinsender (FR)
```

Ein Modul, das sich nicht laden lässt, wird protokolliert und übersprungen —
die übrigen Quellen laufen weiter.

## Ein- und Ausschalten

Geladene Quellen stehen in der Tabelle `module_states` und lassen sich dort
abschalten. Eine Quelle, die dort noch nicht steht, gilt als aktiv — dein neues
Modul funktioniert also, bevor jemand die Einstellungen öffnet.
