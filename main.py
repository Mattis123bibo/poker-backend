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

POKER_RULES = """
═══ TEXAS HOLD'EM POKER REGELN — STRIKT EINHALTEN ═══

HANDSTÄRKEN (von schwach nach stark):
1. High Card
2. One Pair
3. Two Pair
4. Three of a Kind (Set = Pocket Pair + 1 Board / Trips = 1 Hole Card + 2 Board)
5. Straight (5 aufeinanderfolgende Karten, Ass kann hoch A-K-Q-J-T oder tief A-2-3-4-5 sein)
6. Flush (5 Karten gleicher Farbe)
7. Full House (3+2)
8. Four of a Kind
9. Straight Flush
10. Royal Flush (A-K-Q-J-T gleiche Farbe)

PAIR-TYPEN KORREKT BESTIMMEN:
Kartenwerte absteigend: A > K > Q > J > T > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2
• OVERPAIR = Pocket Pair höher als ALLE Board-Karten (z.B. KK auf Board Q-7-2)
• TOP PAIR = eine Hole Card bildet Paar mit der HÖCHSTEN Board-Karte
• MIDDLE PAIR = Paar mit der zweithohen Board-Karte
• BOTTOM PAIR = Paar mit der niedrigsten Board-Karte
• TOP TWO PAIR = die zwei höchsten Board-Karten als Paar
• BOTTOM TWO PAIR = niedrigere Board-Karten als Paar

STRAIGHT KORREKT PRÜFEN:
Schritt 1: Alle 5 Karten auflisten (2 Hole Cards + Board)
Schritt 2: Gibt es 5 aufeinanderfolgende Werte?
Schritt 3: Welche ist die HÖCHSTE mögliche Straight auf diesem Board?

NUTS KORREKT BESTIMMEN:
NUTS = die absolut bestmögliche Hand die auf diesem Board möglich ist
• Für Nuts Straight: Was ist die höchstmögliche Straight auf diesem Board?
  Beispiel: Board 9♣ Q♥ J♣ T♠ → höchste mögliche Straight = A-K-Q-J-T (braucht A+K)
  → Wenn ich K+J habe, mache ich 9-T-J-Q-K Straight, aber NICHT Nuts (A-K wäre Nuts)
• Für Nuts Flush: höchste Flush-Karte der Farbe die am Board möglich ist
• Immer prüfen ob eine bessere Hand möglich ist!

DRAWS KORREKT BENENNEN:
• Flush Draw = 4 Karten gleicher Farbe, 1 fehlt
• OESD (Open Ended Straight Draw) = 4 aufeinanderfolgende Karten, beide Seiten offen (8 Outs)
• Gutshot = 4 Karten mit Lücke in der Mitte (4 Outs)
• Combo Draw = Flush Draw + Straight Draw gleichzeitig (sehr stark, 15+ Outs)

GEWINNWAHRSCHEINLICHKEIT — REALISTISCH:
Preflop typische Equities:
• Premium Pairs (AA,KK): 80%+ Heads-Up
• AK: 65% vs random hand
• Mittlere Pairs (77-TT): 55-65%

Postflop:
• Nuts oder nahe Nuts: 80-95%
• Starke gemachte Hand (Top Pair Top Kicker): 60-75%
• Middle Pair: 40-55%
• Draw (Flush/Straight): 30-40% am Flop, 20% am Turn
• Schwache Hand / Luft: 15-30%
• Gegen mehr Gegner: Equity sinkt entsprechend

BOARD-TEXTUR:
• NASS = viele Draws möglich (connected, flush-möglich): z.B. 9♣ T♥ J♣
• TROCKEN = wenige Draws: z.B. K♦ 7♣ 2♥
• MONOTON = alle gleiche Farbe (sehr flush-gefährlich)
• GEPAART = ein Paar am Board (Full House / Quads möglich)

AKTIONS-EMPFEHLUNG:
• Raise/Bet: Starke Hands für Value, Draws mit Equity + Fold Equity
• Call: Mittlere Hands, gute Draws mit Pot Odds
• Check: Schwache Hands, Kontrolle halten, Trap mit starken Hands
• Fold: Schwache Hands ohne Draws, schlechte Pot Odds

POT ODDS & SIZING:
• Typische Bet-Größen: 33% Pot (klein), 50-60% Pot (standard), 75-100% Pot (groß), Overbet >100%
• Draws brauchen gute Pot Odds: Flush Draw 4:1, Gutshot 10:1
"""

IMAGE_PROMPT = POKER_RULES + """
═══ BILDANALYSE ═══

SCHRITT 1 — HOLE CARDS (vorne unten im Bild):
Lies jeden Wert oben links ab, bestimme Farbe genau:
ROT: ♥ Herz (Herz-Symbol), ♦ Karo (Raute)
SCHWARZ: ♠ Pik (Spaten, oben spitz), ♣ Kreuz (Kleeblatt, 3 runde Kreise)
- Karte 1: Wert + Farbe
- Karte 2: Wert + Farbe

SCHRITT 2 — BOARD (Tischmitte, STRIKT von LINKS nach RECHTS):
Flop=3, Turn=4, River=5 Karten
- Jede Karte einzeln beschreiben
- Mittlere Karte NICHT übersehen!
- Reihenfolge NICHT verändern!
- Kleine umgedrehte Zahl unten rechts auf der Karte = IGNORIEREN (gehört zur selben Karte)

SCHRITT 3 — GEGNER:
Verdeckte Karten (Kartenrücken) zählen → jeder Stapel = 1 Gegner
Keine verdeckten Karten sichtbar → opponents = 1

SCHRITT 4 — ANALYSE nach obigen Poker-Regeln:
1. Alle 5+ Karten auflisten und beste Hand bestimmen
2. Ist es Nuts? Was wäre die Nuts auf diesem Board?
3. Board-Textur bestimmen
4. Realistischen Win% berechnen
5. Optimale Aktion bestimmen

Antworte NUR als JSON:
{
  "myHand": "K♠ J♥",
  "myHandConfidence": "sicher",
  "board": "9♣ Q♥ J♣ T♠",
  "boardStage": "Turn",
  "opponents": 1,
  "position": "unbekannt",
  "winPct": 72,
  "handStrength": "Sehr Stark",
  "handName": "Straight (9-T-J-Q-K), zweitbeste Straight möglich",
  "isNuts": false,
  "nutsDescription": "Nuts wäre A-K-Q-J-T Broadway Straight (braucht Ass)",
  "action": "Raise",
  "actionReason": "Sehr starke Straight, Value gegen schwächere Straights und Two Pairs",
  "sizing": "75% Pot",
  "boardTexture": "Sehr nass — 4-card Straight möglich, viele Draws",
  "opponentRanges": "AK für Broadway Nuts, K9 für gleiche Straight, QJ für Two Pair, Flush Draws",
  "analysis": "Detaillierte Analyse auf Deutsch mit korrekter Handbewertung, Nuts-Analyse, Gefahren und konkreter Empfehlung.",
  "whatISee": "Hole Cards = [X] [X]. Board links nach rechts = [X] [X] [X] [X]. Verdeckte Karten = X Stapel."
}"""

RECALC_PROMPT = POKER_RULES + """
═══ ANALYSE DIESER HAND ═══

MEINE HOLE CARDS: {myHand}
BOARD: {board}
BOARD PHASE: {boardStage}
ANZAHL GEGNER: {opponents}

Führe folgende Schritte durch:
1. Liste alle Karten auf: {myHand} + {board}
2. Bestimme die beste Hand aus diesen Karten
3. Bestimme die Nuts auf diesem Board — was ist die bestmögliche Hand?
4. Ist meine Hand die Nuts? Wenn nicht, was wäre besser?
5. Bestimme Board-Textur (nass/trocken/monoton/gepaart)
6. Berechne realistischen Win% gegen {opponents} Gegner mit typischen Ranges
7. Empfehle optimale Aktion mit Begründung und Sizing

Antworte NUR als JSON:
{{
  "myHand": "{myHand}",
  "board": "{board}",
  "boardStage": "{boardStage}",
  "opponents": {opponents},
  "winPct": 72,
  "handStrength": "Sehr Stark",
  "handName": "Straight (9-T-J-Q-K)",
  "isNuts": false,
  "nutsDescription": "Nuts wäre Broadway Straight A-K-Q-J-T",
  "action": "Raise",
  "actionReason": "Sehr starke Straight, Value gegen schwächere Hands",
  "sizing": "75% Pot",
  "boardTexture": "Sehr nass",
  "opponentRanges": "AK für Broadway, QJ für Two Pair, Flush Draws",
  "analysis": "Detaillierte Analyse auf Deutsch mit allen relevanten Aspekten.",
  "whatISee": ""
}}"""

class Override(BaseModel):
    myHand: str = ""
    board: str = ""
    opponents: int = 1
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
            json={"model":"claude-opus-4-5","max_tokens":2000,"messages":messages}
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
