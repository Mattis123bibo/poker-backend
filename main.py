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

═══ REGEL #1 — JEDE KARTE NUR EINMAL ZÄHLEN ═══
Jede Spielkarte zeigt ihren Wert ZWEIMAL auf derselben Karte:
• Oben links: große Zahl — der ECHTE Wert
• Unten rechts: DIESELBE Zahl, 180° gedreht — KEINE separate Karte, IGNORIEREN!
BEISPIEL: Eine 9 hat unten rechts eine umgedrehte 9 die wie 6 aussieht → NICHT als extra Karte zählen!

═══ FARBEN-ERKENNUNG ═══
ROT: ♥ HERZ (Herz-Symbol), ♦ KARO (Raute)
SCHWARZ: ♠ PIK (Spaten, oben spitz), ♣ KREUZ (Kleeblatt, 3 runde Kreise)

═══ POSITIONEN ═══
• MEINE 2 HOLE CARDS: Ganz vorne unten im Bild
• BOARD: Offene Karten in der Tischmitte — Flop=3, Turn=4, River=5
• Nur tatsächlich separate physische Karten zählen!

═══ GEGNER ═══
Zähle SPIELER nicht Karten. Jeder Gegner = 2 verdeckte Karten.

═══ ANALYSE ═══
Gewinnwahrscheinlichkeit %, Handstärke, Aktion (Raise/Call/Check/Fold), Sizing, Gegner-Ranges.

Antworte NUR als JSON:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "J♦ 9♣ 3♥",
  "boardStage": "Flop",
  "opponents": 2,
  "position": "BTN",
  "winPct": 58,
  "handStrength": "Stark",
  "handName": "Top Pair Top Kicker",
  "action": "Raise",
  "actionReason": "Top Pair Top Kicker, Value gegen Draws",
  "sizing": "60% Pot",
  "opponentRanges": "Pocket Pairs 77+, Broadway AJ+, Suited Connectors 87s+",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards = X, Board = X Karten, Gegner = X"
}"""

RECALC_PROMPT = """Du bist ein professioneller Texas Hold'em Poker-Analyst.

Analysiere diese Hand und gib eine vollständige Auswertung:

MEINE HOLE CARDS: {myHand}
BOARD: {board}
ANZAHL GEGNER: {opponents}

Berechne:
- Gewinnwahrscheinlichkeit % gegen typische Ranges dieser Gegneranzahl
- Aktuelle Handstärke mit Name (z.B. "Top Pair", "Flush Draw", "Set", "Straight")
- Optimale Aktion: Raise / Call / Check / Fold
- Bet Sizing Empfehlung
- Typische Gegner-Ranges und warum
- Detaillierte Analyse auf Deutsch

Antworte NUR als JSON:
{
  "myHand": "{myHand}",
  "board": "{board}",
  "boardStage": "{boardStage}",
  "opponents": {opponents},
  "winPct": 58,
  "handStrength": "Stark",
  "handName": "Top Pair Top Kicker",
  "action": "Raise",
  "actionReason": "Value gegen Draws und schwächere Hands",
  "sizing": "60% Pot",
  "opponentRanges": "Pocket Pairs 77+, Broadway AJ+, Suited Connectors",
  "analysis": "Detaillierte Analyse auf Deutsch mit konkreten Empfehlungen.",
  "whatISee": ""
}"""

class Override(BaseModel):
    myHand: str = ""
    board: str = ""
    opponents: int = 2

class ImageRequest(BaseModel):
    image: str
    override: Optional[Override] = None

def board_stage(board: str) -> str:
    cards = re.findall(r'[AKQJT2-9]{1,2}[♠♥♦♣]', board)
    return {0:"Preflop",3:"Flop",4:"Turn",5:"River"}.get(len(cards),"Flop")

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=45) as client:
        if req.override:
            # Manual recalc with corrected cards
            stage = board_stage(req.override.board)
            board_display = req.override.board if req.override.board else "Kein Board (Preflop)"
            prompt = RECALC_PROMPT.format(
                myHand=req.override.myHand or "Unbekannt",
                board=board_display,
                boardStage=stage,
                opponents=req.override.opponents
            )
            messages = [{"role":"user","content":[{"type":"text","text":prompt}]}]
        else:
            # Image analysis
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
