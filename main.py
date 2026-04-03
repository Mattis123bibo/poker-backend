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

═══ SCHRITT 1: KARTEN EINZELN ZÄHLEN UND BESCHREIBEN ═══
Bevor du irgendwas analysierst, beschreibe JEDE sichtbare physische Karte einzeln:

MEINE HOLE CARDS (vorne unten im Bild):
- Karte 1: Wert oben links ablesen, Farbe bestimmen
- Karte 2: Wert oben links ablesen, Farbe bestimmen

BOARD KARTEN (Tischmitte) — REIHENFOLGE STRIKT VON LINKS NACH RECHTS:
Die Karten EXAKT in der Reihenfolge ausgeben wie sie physisch von links nach rechts auf dem Tisch liegen!
NIEMALS die Reihenfolge ändern oder umsortieren!
- Karte 1 (ganz links): Wert + Farbe
- Karte 2 (Mitte): Wert + Farbe  ← diese Karte NICHT übersehen!
- Karte 3 (ganz rechts): Wert + Farbe
- Falls Turn vorhanden, Karte 4: Wert + Farbe
- Falls River vorhanden, Karte 5: Wert + Farbe

WICHTIG: Beim Flop liegen GENAU 3 Karten nebeneinander. Zähle nochmal nach — sind es wirklich 3 separate Karten? Die mittlere Karte darf nicht vergessen werden!

═══ SCHRITT 2: FEHLER VERMEIDEN ═══
• Jede Karte zeigt den Wert ZWEIMAL: oben links (echter Wert) und unten rechts (umgedreht, IGNORIEREN)
• Eine 9 unten rechts sieht aus wie 6 → NICHT als extra Karte zählen
• Keine Karten erfinden die nicht da sind
• Keine Karten weglassen die da sind
• Falls eine Karte schwer lesbar ist: beste Schätzung mit ~ markieren

═══ SCHRITT 3: FARBEN ═══
ROT: ♥ HERZ (Herz-Symbol), ♦ KARO (Raute/Diamant)
SCHWARZ: ♠ PIK (Spaten, oben spitz zulaufend), ♣ KREUZ (Kleeblatt, 3 runde Kreise)

═══ SCHRITT 4: GEGNER ═══
Zähle SPIELER/SITZPLÄTZE, nicht Karten. Jeder Gegner = 2 verdeckte Karten.

═══ SCHRITT 5: ANALYSE ═══
Nur mit den tatsächlich erkannten Karten analysieren — keine Karten erfinden!
• Gewinnwahrscheinlichkeit % gegen typische Ranges
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
  "opponents": 2,
  "position": "BTN",
  "winPct": 55,
  "handStrength": "Mittel",
  "handName": "Overcards",
  "action": "Check",
  "actionReason": "Kein Treffer, Board sehr stark für Gegner",
  "sizing": "",
  "opponentRanges": "Pocket Pairs, Broadway-Karten, Suited Connectors",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards vorne = [Karte1] [Karte2]. Board von links nach rechts = [Karte1] [Karte2] [Karte3]. Gegner-Sitzplätze = X."
}"""

RECALC_PROMPT = """Du bist ein professioneller Texas Hold'em Poker-Analyst.

Analysiere diese exakte Hand:
MEINE HOLE CARDS: {myHand}
BOARD: {board}
BOARD PHASE: {boardStage}
ANZAHL GEGNER: {opponents}

Berechne präzise:
- Gewinnwahrscheinlichkeit % gegen typische Ranges
- Aktuelle Handstärke mit Name (Flush Draw, Set, Two Pair, usw.)
- Optimale Aktion: Raise / Call / Check / Fold mit Begründung
- Bet Sizing Empfehlung
- Typische Gegner-Ranges in dieser Situation
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
  "analysis": "Detaillierte Analyse auf Deutsch mit konkreten Empfehlungen.",
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
