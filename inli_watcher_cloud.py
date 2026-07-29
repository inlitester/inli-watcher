#!/usr/bin/env python3
"""
inli_watcher_cloud.py — Version cloud (GitHub Actions) du watcher in'li.

Contrairement à la version locale, ce script ne boucle pas à l'infini :
il fait UNE SEULE vérification puis s'arrête. C'est GitHub Actions qui se
charge de le relancer toutes les X minutes, même PC éteint.

Notifications envoyées via un bot Telegram (au lieu d'un toast Windows).

Critères : Paris, >= 28 m², <= 1100 €, studio/1 pièce ou 2 pièces
"""

import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG — critères de recherche
# ---------------------------------------------------------------------------
SEARCH_URL = "https://www.inli.fr/locations/offres/paris_d:75/"
MIN_SURFACE_M2 = 28
MAX_SURFACE_M2 = None
MAX_LOYER_EUR = 1100
PIECES_AUTORISEES = {1, 2}

# Ces deux valeurs sont lues depuis les "secrets" GitHub (jamais écrites en dur ici)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_listings.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# ---------------------------------------------------------------------------


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def fetch_listings():
    resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    listings = []
    for a in soup.find_all("a", href=re.compile(r"/locations/offre/paris/")):
        href = a.get("href")
        text = a.get_text(" ", strip=True)
        if not text:
            continue

        prix_match = re.search(r"([\d\s]+)\s*€", text)
        pieces_match = re.search(r"(\d+)\s*pi[eè]ces?", text)
        is_studio = re.search(r"\bStudio\b", text, re.IGNORECASE) is not None
        surface_match = re.search(r"([\d.,]+)\s*m²", text)
        quartier_match = re.search(r"(Paris\s*\d+(?:er|ème|eme))", text)

        if not surface_match:
            continue

        if pieces_match:
            pieces_value = pieces_match.group(1)
        elif is_studio:
            pieces_value = "1"
        else:
            pieces_value = None

        listing_id = href.rstrip("/").split("/")[-1]
        listings.append({
            "id": listing_id,
            "url": "https://www.inli.fr" + href if href.startswith("/") else href,
            "prix": prix_match.group(1).replace(" ", "").strip() if prix_match else None,
            "pieces": pieces_value,
            "surface": float(surface_match.group(1).replace(",", ".")) if surface_match else None,
            "quartier": quartier_match.group(1) if quartier_match else None,
        })

    dedup = {l["id"]: l for l in listings}
    return list(dedup.values())


def matches_criteria(listing):
    if listing["surface"] is None or listing["surface"] < MIN_SURFACE_M2:
        return False
    if MAX_SURFACE_M2 and listing["surface"] > MAX_SURFACE_M2:
        return False
    if MAX_LOYER_EUR and listing["prix"]:
        try:
            if float(listing["prix"]) > MAX_LOYER_EUR:
                return False
        except ValueError:
            pass
    if PIECES_AUTORISEES:
        if listing["pieces"] is None:
            return False
        try:
            if int(listing["pieces"]) not in PIECES_AUTORISEES:
                return False
        except ValueError:
            return False
    return True


def send_telegram(listing):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant — impossible de notifier.")
        return

    text = (
        f"🏠 *Nouvelle annonce in'li !*\n"
        f"{listing['quartier'] or 'Paris'} — {listing['surface']} m² — {listing['prix'] or '?'} €\n"
        f"{listing['url']}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=15)
        if r.status_code != 200:
            print(f"[!] Erreur envoi Telegram : {r.status_code} {r.text}")
    except requests.RequestException as e:
        print(f"[!] Erreur réseau Telegram : {e}")


def main():
    seen = load_seen()
    is_first_run = (len(seen) == 0)
    listings = fetch_listings()
    new_matches = []

    for listing in listings:
        if listing["id"] in seen:
            continue
        seen[listing["id"]] = {}
        if matches_criteria(listing) and not is_first_run:
            new_matches.append(listing)

    save_seen(seen)

    if is_first_run:
        print(f"Premier lancement : {len(listings)} annonces enregistrées comme référence.")
    else:
        for listing in new_matches:
            print(f"Nouveau match : {listing['url']}")
            send_telegram(listing)
        if not new_matches:
            print(f"Rien de nouveau ({len(listings)} annonces vues au total).")


if __name__ == "__main__":
    main()
