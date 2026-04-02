import os
import json
import httpx
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

PROMPT = """Du bist ein Poker-Experte. Analysiere das Bild eines Pokertisches oder von Karten.

SCHRITT 1 - KARTEN ERKENNEN:
Erkenne Wert (A K Q J T 9 8 7 6 5 4 3 2) und Farbe (♠ ♥ ♦ ♣) jeder Karte.
Auch bei schlechter Qualität: gib deine beste Schätzung an.

SCHRITT 2 - SITUATION ERKENNEN:
- Welche 2 Karten sind die Startkarten des Spielers (hole cards)?
- Gibt es Tischkarten (Board: Flop/Turn/River)?
- Wie viele Gegner sind erkennbar?

SCHRITT 3 - ANALYSE:
- Gewinnwahrscheinlichkeit % gegen typische Ranges
- Handstärke und beste Aktion

Antworte NUR als JSON ohne Text davor oder danach:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "",
  "boardStage": "Preflop",
  "opponents": 2,
  "position": "unbekannt",
  "winPct": 67,
  "handStrength": "Premium",
  "handName": "Big Slick",
  "action": "Raise",
  "actionReason": "Premium Hand, immer 3-Bet preflop",
  "opponentRanges": "Gegner spielen typisch: Pocket Pairs, Broadway-Karten, Suited Connectors",
  "analysis": "Vollständige deutsche Analyse der Hand, Board-Textur, Empfehlung.",
  "whatISee": "Kurze Beschreibung was ich im Bild sehe"
}"""

class ImageRequest(BaseModel):
    image: str  # base64 jpeg

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-4-5",
                "max_tokens": 1200,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": req.image}},
                        {"type": "text", "text": PROMPT}
                    ]
                }]
            }
        )
    data = resp.json()
    raw = data.get("content", [{}])[0].get("text", "")
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        import re
        match = re.search(r'\{[\s\S]*\}', clean)
        parsed = json.loads(match.group(0) if match else clean)
        return parsed
    except Exception:
        return {"error": "Parse error", "raw": raw}

@app.get("/")
def root():
    return {"status": "Poker AI Backend online"}
