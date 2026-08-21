# PBArr

Holt Sendungen aus öffentlich-rechtlichen Mediatheken und legt sie so ab, dass
Plex, Jellyfin und Emby sie erkennen.

Du trägst ein, wie eine Sendung heisst. Den Rest macht PBArr.

```
Name eintragen  →  stündlich suchen  →  filtern  →  herunterladen  →  einsortieren
```

## Was es nicht braucht

Keine TVDB-ID. Keinen Sonarr. Keine Episodennummern.

Das war einmal anders, und es funktionierte nicht: PBArr fragte TVDB nach einer
Episodenliste, Sonarr nach fehlenden Folgen, und lud nur herunter, wo beide sich
auf dieselbe Staffel-/Episodennummer einigten. Sie einigten sich nie. Beide
fragen TVDB unabhängig voneinander und kommen zu unterschiedlichen Zählungen,
und viele Sendungen des öffentlich-rechtlichen Rundfunks stehen dort gar nicht.

Gemessen an einer laufenden Instanz: Sonarr suchte S00, S02, S04 und S08,
zwischengespeichert waren S01, S06 und S07. Keine einzige Überschneidung. Die
tatsächlich verfügbaren Folgen kannte Sonarr überhaupt nicht.

Deshalb kommt die Einordnung jetzt von dem, der die Sendung produziert hat:

1. Die Quelle, wenn sie eine Nummer nennt
2. Sonst der Titel — `Folge 104: Ausgebrannt (S07/E04)` ergibt `S07E04`
3. Sonst das Sendedatum

Alle gängigen Medienserver lesen `JJJJ-MM-TT` an der Stelle, wo sonst `SxxEyy`
steht. Für tägliche Sendungen und Talkshows ist das ohnehin der passendere Weg.

## Ablage

```
Bibliothek/
  Das Gipfeltreffen/
    Season 2026/
      Das Gipfeltreffen - 2026-08-20 - Das Beste kommt noch! (58).mp4
  Hubert und Staller/
    Season 09/
      Hubert und Staller - S09E06 - Folge 138 Jeder Schuss ein Treffer.mp4
```

Den Serienordner erkennt der Medienserver und holt Poster und Beschreibung
selbst — dafür braucht PBArr keine Datenbank abzufragen.

## Ein Eintrag

| Feld | Bedeutung |
|---|---|
| **Name** | Wie die Sendung in der Mediathek heisst |
| Anzeigename | Bestimmt den Ordnernamen, falls abweichend |
| Qualität | `hd`, `normal` oder `low`, mit Rückfallebene |
| Dauer | Trennt ganze Folgen von kurzen Ausschnitten |
| Sender | Leer = alle |
| Ausschlusswörter | Standard: Audiodeskription, Gebärdensprache, klare Sprache |

**Mehrere Namen** trennst du mit `|`. Sendungen werden umbenannt: „Hubert und
Staller" wurde zu „Hubert ohne Staller", beide liegen nebeneinander in der
Mediathek, und den Sammelnamen kennt sie nicht.

```
Hubert und Staller|Hubert ohne Staller
```

## Wohin die Dateien kommen

Standard ist flach im Serienordner:

```
Serien/Das Gipfeltreffen/Das Gipfeltreffen - 2026-08-20 - Das Beste kommt noch!.mp4
Serien/Hubert und Staller/Hubert und Staller - S07E04 - Ausgebrannt.mp4
```

Wer Staffel-Unterordner möchte, stellt das je Sendung auf **„In Staffel-Unterordnern"**
um; dann entsteht `Season 07/` bzw. `Season 2026/` für alles ohne Folgennummer. Beide
Formen lesen Plex, Jellyfin und Emby.

**Liegt die Serie schon in deiner Bibliothek**, benutzt PBArr den vorhandenen Ordner,
statt einen zweiten daneben zu legen. Verglichen wird ohne Rücksicht auf Gross- und
Kleinschreibung, Akzente und Satzzeichen — „Wer weiss denn sowas" und
„Wer weiß denn sowas?" sind derselbe Ordner. Reicht das nicht, weil der Ordner ganz
anders heisst, trägst du ihn bei der Sendung unter **„Ordner in der Bibliothek"** ein.

Die Serie selbst erkennt der Medienserver über den Ordnernamen und holt sich Poster
und Beschreibung von dort, wo er seine Metadaten bezieht. PBArr liefert keine
Metadaten und braucht dafür auch keine Serien-ID.

## Vorschau statt Suche

Bevor du einen Eintrag anlegst, zeigt die Vorschau, was er einbringen würde —
und **warum** etwas aussortiert wird:

```
109 Treffer, 0 passend
✗ 2026-05-02  10 min  ORF  Klein gegen groß: Säulenparcours…  zu kurz (10 < 60 min)
```

Damit siehst du sofort, dass der Dauerfilter danebenliegt, statt zu rätseln,
warum nichts ankommt.

## Installation

```yaml
services:
  pbarr:
    image: ghcr.io/seliku/pbarr:stable
    container_name: pbarr
    restart: unless-stopped
    ports:
      - "8070:8000"
    environment:
      DATABASE_URL: postgresql://pbuser:PASSWORT@postgres:5432/pbarr
      LOG_LEVEL: INFO
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - /pfad/zu/deiner/bibliothek:/app/library

  postgres:
    image: postgres:15-alpine
    container_name: pbarr-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: pbuser
      POSTGRES_PASSWORD: PASSWORT
      POSTGRES_DB: pbarr
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Oberfläche unter `http://dein-host:8070`. Datenbank-Migrationen laufen beim
Start von selbst.

## Selbst bauen

```bash
./build.sh                # baut aus der letzten Git-Marke
./build.sh --push         # veröffentlicht als :stable :latest :beta
./build.sh --push 1.2.0   # mit ausdrücklicher Version
```

Nicht `docker build .` von Hand aufrufen. Das Dockerfile hat
`ARG VERSION=0.0.0-dev`, und ohne `--build-arg` nennt sich das fertige Abbild
genau so. Die Aktualisierungsprüfung vergleicht diesen Wert mit der neuesten
Marke auf GitHub — eine Fassung, die sich `0.0.0-dev` nennt, hält sich für immer
veraltet. `build.sh` leitet die Version aus der Git-Marke ab, prüft danach nach,
ob das gebaute Abbild sich auch wirklich so nennt, und veröffentlicht nichts aus
einem Arbeitsbaum mit uneingecheckten Änderungen.

## Andere Länder anbinden

PBArr spricht standardmässig mit MediathekViewWeb, dem gemeinsamen Index von
ARD, ZDF, 3sat, arte, ORF, SRF und den übrigen.

Wer einen Sender aus einem anderen Land anbinden will, schreibt **eine Datei**.
Siehe [docs/module-schreiben.md](docs/module-schreiben.md).

## Was PBArr nicht tut

Es lädt nur, was gerade in der Mediathek liegt. Was depubliziert wurde, ist weg
— dagegen hilft keine Software. Deshalb läuft der Abgleich stündlich statt
täglich.

Ein Link, der dreimal hintereinander scheitert, wird nicht weiter versucht.
Depublizierte Sendungen antworten dauerhaft mit 403 oder 404.

## Lizenz

Siehe [LICENSE](LICENSE).
