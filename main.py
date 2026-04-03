import os
import json
import httpx
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

IMAGE_PROMPT = """Du bist ein professioneller Poker-Bildanalyst für Texas Hold'em.

═══ SCHRITT 1: HOLE CARDS (vorne unten im Bild) ═══
Die 2 Karten ganz vorne unten — lies jeden Wert oben links ab:
- Karte 1: Wert + Farbe
- Karte 2: Wert + Farbe

═══ SCHRITT 2: BOARD (Tischmitte, STRIKT von LINKS nach RECHTS) ═══
Beschreibe jede offene Karte in der Tischmitte einzeln, exakt in der Reihenfolge von links nach rechts:
- Flop = genau 3 Karten, Turn = 4, River = 5
- Die mittlere Karte beim Flop NICHT übersehen!
- Reihenfolge NIEMALS umsortieren!
- Wert immer oben links ablesen — die kleine umgedrehte Zahl unten rechts ist DIESELBE Karte, nicht zählen!

═══ SCHRITT 3: GEGNER ZÄHLEN — SEHR WICHTIG ═══
Schaue aktiv nach verdeckten Karten auf dem Tisch:
• Verdeckte Karten erkennst du an: Kartenrücken (meist rot/blau gemustert), ohne sichtbaren Wert
• Zähle die Anzahl der Stapel/Paare verdeckter Karten — jeder Stapel = 1 Gegner
• Wenn du KEINE verdeckten Karten siehst → opponents = 1 (mindestens 1 Gegner wird angenommen)
• Wenn du z.B. 2 Stapel verdeckter Karten siehst → opponents = 2
• NIE raten oder erfinden — nur zählen was wirklich sichtbar ist!

═══ SCHRITT 4: FEHLER VERMEIDEN ═══
• Keine Karten erfinden
• Keine Karten weglassen
• Reihenfolge exakt von links nach rechts

═══ SCHRITT 5: ANALYSE ═══
Nur mit tatsächlich erkannten Karten analysieren:
• Gewinnwahrscheinlichkeit % (falls opponents=0: gegen 1-3 typische Gegner schätzen)
• Handstärke mit Name
• Aktion: Raise / Call / Check / Fold
• Sizing (z.B. "60% Pot")
• Gegner-Ranges

Antworte NUR als JSON:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "9♣ J♥ J♦",
  "boardStage": "Flop",
  "opponents": 1,
  "opponentsConfidence": "keine verdeckten Karten sichtbar, 1 Gegner angenommen",
  "position": "unbekannt",
  "winPct": 62,
  "handStrength": "Stark",
  "handName": "Top Pair Top Kicker",
  "action": "Raise",
  "actionReason": "Starke Hand, Value Bet",
  "sizing": "60% Pot",
  "opponentRanges": "Typische Ranges: Pocket Pairs 77+, Broadway AJ+, Suited Connectors",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards = [X] [X]. Board links nach rechts = [X] [X] [X]. Verdeckte Karten sichtbar: ja/nein, Anzahl Gegner-Stapel = X."
}"""

RECALC_PROMPT = """Du bist ein professioneller Texas Hold'em Poker-Analyst.

Analysiere diese exakte Hand:
MEINE HOLE CARDS: {myHand}
BOARD: {board}
BOARD PHASE: {boardStage}
ANZAHL GEGNER: {opponents}

Berechne präzise:
- Gewinnwahrscheinlichkeit % gegen typische Ranges
- Aktuelle Handstärke mit Name
- Optimale Aktion: Raise / Call / Check / Fold mit Begründung
- Bet Sizing Empfehlung
- Typische Gegner-Ranges
- Detaillierte Analyse auf Deutsch

Antworte NUR als JSON:
{{
  "myHand": "{myHand}",
  "board": "{board}",
  "boardStage": "{boardStage}",
  "opponents": {opponents},
  "winPct": 55,
  "handStrength": "Mittel",
  "handName": "Top Pair",
  "action": "Raise",
  "actionReason": "Value gegen schwächere Hands",
  "sizing": "60% Pot",
  "opponentRanges": "Pocket Pairs 77+, Broadway AJ+, Suited Connectors",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": ""
}}"""

class Override(BaseModel):
    myHand: str = ""
    board: str = ""
    opponents: int = 2
    boardStage: str = "Preflop"

class ImageRequest(BaseModel):
    image: str
    override: Optional[Override] = None

def get_board_stage(board: str) -> str:
    cards = re.findall(r'[AKQJT2-9]{1,2}[♠♥♦♣]', board)
    return {0:"Preflop",3:"Flop",4:"Turn",5:"River"}.get(len(cards),"Flop")

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=45) as client:
        if req.override:
            stage = req.override.boardStage or get_board_stage(req.override.board)
            board_display = req.override.board if req.override.board else "Kein Board (Preflop)"
            prompt = RECALC_PROMPT.format(
                myHand=req.override.myHand or "Unbekannt",
                board=board_display,
                boardStage=stage,
                opponents=req.override.opponents
            )
            messages = [{"role":"user","content":[{"type":"text","text":prompt}]}]
        else:
            messages = [{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":req.image}},
                {"type":"text","text":IMAGE_PROMPT}
            ]}]

        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model":"claude-opus-4-5","max_tokens":1500,"messages":messages}
        )

    data = resp.json()
    raw = data.get("content",[{}])[0].get("text","")
    try:
        clean = raw.replace("```json","").replace("```","").strip()
        match = re.search(r'\{[\s\S]*\}', clean)
        parsed = json.loads(match.group(0) if match else clean)
        return parsed
    except Exception:
        return {"error":"Parse error","raw":raw}

@app.get("/")
def root():
    return {"status":"Poker AI Backend online"}
