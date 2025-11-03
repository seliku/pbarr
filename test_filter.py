#!/usr/bin/env python3

import sys
sys.path.append('app')

from app.services.episode_matcher import EpisodeMatcher

def test_filter():
    matcher = EpisodeMatcher(None)  # Keine DB nötig für Filter-Test

    # Test-Episoden
    test_episodes = [
        {
            'title': 'Doppelleben (258)',
            'description': 'Eine spannende Episode'
        },
        {
            'title': 'Doppelleben (258) (Audiodeskription)',
            'description': 'Eine spannende Episode'
        },
        {
            'title': 'Doppelleben (258) klare Sprache',
            'description': 'Eine spannende Episode'
        }
    ]

    exclude_keywords = "klare Sprache,Audiodeskription,Gebärdensprache"

    print("Teste Filter mit exclude_keywords:", exclude_keywords)
    print()

    for ep in test_episodes:
        result = matcher.filter_excluded_keywords(ep, exclude_keywords)
        status = "✅ DURCHGELASSEN" if result else "🚫 GEFILTERT"
        print(f"Titel: '{ep['title']}'")
        print(f"  Ergebnis: {status}")
        print()

if __name__ == "__main__":
    test_filter()
