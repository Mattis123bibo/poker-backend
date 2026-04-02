import os
import json
import httpx
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

PROMPT = """Du bist ein professioneller Poker-Analyst mit perfekter Kartenerkennungs-Fähigkeit. Analysiere dieses Texas Hold'em Pokertisch-Bild.

KARTEN-ERKENNUNG — SEHR WICHTIG:
Unterscheide die 4 Farben GENAU anhand der Symbole und Farbe:
- ♠ Pik = SCHWARZ, Pfeil-/Spaten-Symbol
- ♣ Kreuz = SCHWARZ, Kleeblatt-Symbol  
- ♥ Herz = ROT, Herz-Symbol
- ♦ Karo = ROT, Raute/Diamant-Symbol
Schwarz vs. Rot ist der wichtigste Unterschied — schaue genau hin!

POSITION DER KARTEN IM BILD:
- MEINE 2 HOLE CARDS: Die Karten GANZ VORNE UNTEN im Bild — das sind immer die eigenen Startkarten des Spielers
- BOARD KARTEN: Die Karten in der MITTE DES TISCHES (Flop = 3 Karten, Turn = 4, River = 5)
- GEGNER KARTEN: Verdeckte oder andere Karten weiter hinten/oben im Bild

ERKENNE:
1. Meine 2 Hole Cards (vorne unten) — Wert + Farbe exakt
2. Board Karten (Tischmitte) — alle sichtbaren Gemeinschaftskarten
3. Anzahl Gegner am Tisch
4. Aktuelle Spielphase (Preflop/Flop/Turn/River)

ANALYSE (Texas Hold'em):
- Gewinnwahrscheinlichkeit % gegen typische Gegner-Ranges
- Stärke der aktuellen Hand
- Optimale Aktion mit Begründung
- Pot Odds und Sizing-Empfehlung falls relevant

Antworte NUR als JSON ohne Text davor oder danach:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "J♦ 9♣ 3♥",
  "boardStage": "Flop",
  "opponents": 3,
  "position": "BTN",
  "winPct": 58,
  "handStrength": "Stark",
  "handName": "Top Pair Top Kicker",
  "action": "Raise",
  "actionReason": "Top Pair Top Kicker, Value gegen Draws und schwächere Aces",
  "sizing": "2/3 Pot",
  "opponentRanges": "Typische Ranges: Pocket Pairs 77+, Broadway-Karten AJ+, Suited Connectors 87s+",
  "analysis": "Vollständige Analyse auf Deutsch: Hand-Stärke, Board-Textur (nass/trocken), Empfehlung mit Reasoning, was bei Raise/Call/Fold der Gegner zu tun ist.",
  "whatISee": "Ich sehe: [genaue Beschreibung der erkannten Karten und Tischsituation]"
}"""

class ImageRequest(BaseModel):
    image: str

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-4-5",
                "max_tokens": 1500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": req.image
                            }
                        },
                        {"type": "text", "text": PROMPT}
                    ]
                }]
            }
        )
    data = resp.json()
    raw = data.get("content", [{}])[0].get("text", "")
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{[\s\S]*\}', clean)
        parsed = json.loads(match.group(0) if match else clean)
        return parsed
    except Exception:
        return {"error": "Parse error", "raw": raw}

@app.get("/")
def root():
    return {"status": "Poker AI Backend online"}
