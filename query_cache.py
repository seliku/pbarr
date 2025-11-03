#!/usr/bin/env python3

import os
import sys
sys.path.append('app')

from app.database import SessionLocal, init_db
from app.models.mediathek_cache import MediathekCache
from app.models.watch_list import WatchList

def main():
    # Stelle sicher, dass DB initialisiert ist
    init_db()

    # Erstelle Session
    db = SessionLocal()

    try:
        # Zuerst prüfe alle Serien in watch_list
        shows = db.query(WatchList).all()
        print("Verfügbare Serien in watch_list:")
        for show in shows:
            print(f"  TVDB ID: {show.tvdb_id}, Name: {show.show_name}, Sonarr ID: {show.sonarr_series_id}")
        print()

        # Suche nach Serie mit TVDB ID 93221
        target_show = db.query(WatchList).filter(WatchList.tvdb_id == '93221').first()
        if not target_show:
            print("Keine Serie mit TVDB ID 93221 in watch_list gefunden.")
            return

        print(f"Gefundene Serie: {target_show.show_name} (TVDB ID: {target_show.tvdb_id})")
        print(f"  Tagged in Sonarr: {target_show.tagged_in_sonarr}")
        print(f"  Episodes found: {target_show.episodes_found}")
        print(f"  Mediathek episodes count: {target_show.mediathek_episodes_count}")
        print()

        # Zuerst prüfe alle tvdb_ids in der Tabelle
        all_tvdb_ids = db.query(MediathekCache.tvdb_id).distinct().all()
        print(f"Verfügbare TVDB IDs im Cache: {[id[0] for id in all_tvdb_ids]}")

        # Zähle alle Einträge pro TVDB ID
        for tvdb_id in [id[0] for id in all_tvdb_ids]:
            count = db.query(MediathekCache).filter(MediathekCache.tvdb_id == tvdb_id).count()
            matched_count = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id,
                MediathekCache.season.isnot(None)
            ).count()
            unmatched_count = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id,
                MediathekCache.season.is_(None)
            ).count()
            print(f"  TVDB {tvdb_id}: {count} total ({matched_count} matched, {unmatched_count} unmatched)")

        # Prüfe alle Einträge in der Tabelle (auch wenn nicht gefiltert nach TVDB ID)
        total_count = db.query(MediathekCache).count()
        print(f"Gesamt-Einträge in mediathek_cache: {total_count}")

        if total_count > 0:
            # Zeige die neuesten 5 Einträge
            latest_entries = db.query(MediathekCache).order_by(MediathekCache.created_at.desc()).limit(5).all()
            print("Neueste 5 Cache-Einträge:")
            for entry in latest_entries:
                status = "matched" if entry.season else "unmatched"
                print(f"  ID {entry.id}: TVDB {entry.tvdb_id}, '{entry.mediathek_title}' ({status}) - {entry.created_at}")

        # Abfrage für die gefundene TVDB ID - ALLE Einträge (matched und unmatched)
        all_results = db.query(MediathekCache).filter(MediathekCache.tvdb_id == target_show.tvdb_id).all()

        if not all_results:
            print(f"Keine Cache-Einträge für Serie {target_show.show_name} gefunden.")
            print("\nDebugging-Info:")
            print("- Prüfe TVDB Cache...")

            # Prüfe TVDB Cache
            from app.models.tvdb_cache import TVDBCache
            tvdb_entries = db.query(TVDBCache).filter(TVDBCache.tvdb_id == target_show.tvdb_id).limit(5).all()
            print(f"  TVDB Cache hat {len(tvdb_entries)} Einträge für {target_show.tvdb_id}")
            for entry in tvdb_entries:
                print(f"    S{entry.season}E{entry.episode} - {entry.episode_name} - Air: {entry.aired_date}")

            print("- Prüfe Mediathek-Suche...")
            print("  (Aus Logs: 50 Ergebnisse gefunden, aber gefiltert)")
            return

        # Separate matched und unmatched
        matched_results = [r for r in all_results if r.season is not None]
        unmatched_results = [r for r in all_results if r.season is None]

        print(f"Gefundene Cache-Einträge für Serie 93221: {len(all_results)}")
        print(f"  - Matched: {len(matched_results)}")
        print(f"  - Unmatched: {len(unmatched_results)}")
        print()

        if matched_results:
            print("MATCHED EPISODES:")
            print("-" * 80)
            for entry in matched_results:
                print(f"ID: {entry.id}")
                print(f"TVDB ID: {entry.tvdb_id}")
                print(f"Season: {entry.season}")
                print(f"Episode: {entry.episode}")
                print(f"Episode Title: {entry.episode_title}")
                print(f"Mediathek Title: {entry.mediathek_title}")
                print(f"Platform: {entry.mediathek_platform}")
                print(f"Media URL: {entry.media_url}")
                print(f"Quality: {entry.quality}")
                print(f"Match Confidence: {entry.match_confidence}")
                print(f"Match Type: {entry.match_type}")
                print(f"Created At: {entry.created_at}")
                print(f"Expires At: {entry.expires_at}")
                print("-" * 40)

        if unmatched_results:
            print("UNMATCHED EPISODES (gecached für zukünftiges Matching):")
            print("-" * 80)
            for entry in unmatched_results[:10]:  # Zeige nur erste 10
                print(f"ID: {entry.id}")
                print(f"Mediathek Title: {entry.mediathek_title}")
                print(f"Platform: {entry.mediathek_platform}")
                print(f"Media URL: {entry.media_url}")
                print(f"Quality: {entry.quality}")
                print(f"Created At: {entry.created_at}")
                print("-" * 40)

            if len(unmatched_results) > 10:
                print(f"... und {len(unmatched_results) - 10} weitere unmatched Episoden")

    finally:
        db.close()

if __name__ == "__main__":
    main()
