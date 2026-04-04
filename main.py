import os
import json
import httpx
import re
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from treys import Card, Evaluator, Deck

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
evaluator = Evaluator()

SUIT_MAP = {'♠':'s', '♥':'h', '♦':'d', '♣':'c'}
VAL_MAP = {'A':'A','K':'K','Q':'Q','J':'J','T':'T',
           '9':'9','8':'8','7':'7','6':'6','5':'5','4':'4','3':'3','2':'2'}

def to_treys(card_str):
    card_str = card_str.strip()
    suit = card_str[-1]
    val = card_str[:-1]
    if val == '10': val = 'T'
    t_suit = SUIT_MAP.get(suit)
    t_val = VAL_MAP.get(val)
    if not t_suit or not t_val:
        return None
    try:
        return Card.new(t_val + t_suit)
    except:
        return None

def parse_cards(card_string):
    if not card_string:
        return []
    cards = re.findall(r'[AKQJT2-9]{1,2}[♠♥♦♣]', card_string)
    result = []
    for c in cards:
        t = to_treys(c)
        if t:
            result.append(t)
    return result

def simulate_win_pct(hole_cards, board_cards, num_opponents=1, simulations=3000):
    if len(hole_cards) != 2:
        return 0
    wins = 0
    ties = 0
    known = set(hole_cards + board_cards)

    for _ in range(simulations):
        deck = Deck()
        deck.cards = [c for c in deck.cards if c not in known]
        random.shuffle(deck.cards)

        needed_board = 5 - len(board_cards)
        sim_board = board_cards + deck.cards[:needed_board]
        remaining = deck.cards[needed_board:]

        opp_hands = []
        idx = 0
        for i in range(num_opponents):
            if idx + 2 > len(remaining):
                break
            opp_hands.append([remaining[idx], remaining[idx+1]])
            idx += 2

        if len(opp_hands) < num_opponents:
            continue

        try:
            my_rank = evaluator.evaluate(sim_board, hole_cards)
            opp_ranks = [evaluator.evaluate(sim_board, h) for h in opp_hands]
            if all(my_rank < r for r in opp_ranks):
                wins += 1
            elif my_rank == min(opp_ranks):
                ties += 0.5
        except:
            continue

    return round((wins + ties) / simulations * 100)

def get_hand_info(hole_cards, board_cards):
    if len(hole_cards) != 2 or len(board_cards) < 3:
        return None, None
    try:
        rank = evaluator.evaluate(board_cards, hole_cards)
        rank_class = evaluator.get_rank_class(rank)
        hand_name = evaluator.class_to_string(rank_class)
        # Strength mapping
        if rank_class == 1:   strength = "Sehr Stark"  # Royal Flush
        elif rank_class == 2: strength = "Sehr Stark"  # Straight Flush
        elif rank_class == 3: strength = "Sehr Stark"  # Four of a Kind
        elif rank_class == 4: strength = "Sehr Stark"  # Full House
        elif rank_class == 5: strength = "Stark"       # Flush
        elif rank_class == 6: strength = "Stark"       # Straight
        elif rank_class == 7: strength = "Stark"       # Three of a Kind
        elif rank_class == 8: strength = "Mittel"      # Two Pair
        elif rank_class == 9: strength = "Mittel"      # Pair
        else:                  strength = "Schwach"    # High Card
        return hand_name, strength
    except:
        return None, None

def get_pair_type(hole_cards, board_cards, hand_name):
    if "Pair" not in hand_name:
        return hand_name
    VAL_ORDER = {'A':14,'K':13,'Q':12,'J':11,'T':10,'9':9,'8':8,'7':7,'6':6,'5':5,'4':4,'3':3,'2':2}
    rank_chars = "23456789TJQKA"

    def card_val(c):
        r = Card.get_rank_int(c)
        return VAL_ORDER.get(rank_chars[r], 0)

    hole_vals = sorted([card_val(c) for c in hole_cards], reverse=True)
    board_vals = sorted([card_val(c) for c in board_cards], reverse=True)

    if hole_vals[0] == hole_vals[1]:
        if hole_vals[0] > board_vals[0]:
            return "Overpair"
        return hand_name

    pair_val = None
    for hv in hole_vals:
        if hv in board_vals:
            pair_val = hv
            break

    if pair_val is None:
        return hand_name
    if pair_val == board_vals[0]:
        return "Top Pair"
    elif len(board_vals) > 1 and pair_val == board_vals[1]:
        return "Middle Pair"
    else:
        return "Bottom Pair"

def recommend_action(win_pct, board_stage, num_opponents):
    if win_pct >= 75:
        return "Raise", "Sehr starke Hand — maximaler Value", "75-100% Pot"
    elif win_pct >= 60:
        return "Raise", "Starke Hand — Value Bet", "50-75% Pot"
    elif win_pct >= 45:
        return "Call", "Mittlere Hand — Pot Odds sind ok", "—"
    elif win_pct >= 35:
        return "Check", "Schwache Hand — Kontrolle halten", "—"
    else:
        return "Fold", "Zu schwach — aufgeben", "—"

IMAGE_PROMPT = """Du bist ein Poker-Kartenscanner für Texas Hold'em. Erkenne ALLE Karten auf dem Bild.

FARBEN — FÜR JEDE KARTE PRÜFEN:
ROT: ♥ Herz (Herz-Symbol), ♦ Karo (Raute/Diamant)
SCHWARZ: ♠ Pik (Spaten, oben spitz), ♣ Kreuz (Kleeblatt, 3 runde Kreise)
PFLICHT: Nach Erkennung jede Karte nochmal prüfen — rotes Symbol = NIEMALS ♠ oder ♣!
Bei schlechtem Licht: Rot erscheint dunkel aber ist NIEMALS schwarz!

POSITIONEN IM BILD:
• MEINE HOLE CARDS (myHand): Die 2 Karten GANZ VORNE UNTEN im Bild, nah zur Kamera
  Egal ob Handy quer oder hochkant — es sind IMMER die 2 vordersten Karten!
• BOARD: Offene Karten in der TISCHMITTE, STRIKT von LINKS nach RECHTS lesen
  Flop = genau 3 Karten | Turn = 4 Karten | River = 5 Karten
  Die mittlere Karte beim Flop NICHT vergessen!
  Reihenfolge NIEMALS verändern!
• Kleine umgedrehte Zahl unten rechts auf jeder Karte = IGNORIEREN (gleiche Karte nochmal)
• Eine 9 umgedreht sieht wie 6 aus — NICHT als extra Karte zählen!

GEGNER: Verdeckte Karten (Kartenrücken) zählen → 1 Stapel = 1 Gegner, minimum 1

Antworte NUR als JSON ohne Text davor oder danach:
{
  "myHand": "K♠ 2♥",
  "board": "T♠ 3♠ J♠ A♠",
  "opponents": 2,
  "confidence": "sicher"
}"""

ANALYSIS_PROMPT = """Analysiere diese Texas Hold'em Pokersituation auf Deutsch:

HOLE CARDS: {myHand}
BOARD: {board}
PHASE: {boardStage}
HAND: {handName}
WIN%: {winPct}%
GEGNER: {opponents}

Erkläre kurz und präzise:
1. Warum diese Hand stark/schwach ist
2. Board-Textur
3. Typische Gegner-Ranges
4. Konkrete Empfehlung

Nur Text, kein JSON, max 200 Wörter."""

class Override(BaseModel):
    myHand: str = ""
    board: str = ""
    opponents: int = 1
    boardStage: str = "Preflop"

class ImageRequest(BaseModel):
    image: str
    override: Optional[Override] = None

def get_board_stage(board_cards):
    return {0:"Preflop", 3:"Flop", 4:"Turn", 5:"River"}.get(len(board_cards), "Preflop")

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=60) as client:

        if req.override:
            my_hand_str = req.override.myHand
            board_str = req.override.board
            opponents = req.override.opponents
        else:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-opus-4-5",
                    "max_tokens": 300,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": req.image}},
                            {"type": "text", "text": IMAGE_PROMPT}
                        ]
                    }]
                }
            )
            raw = resp.json().get("content", [{}])[0].get("text", "")
            try:
                clean = raw.replace("```json","").replace("```","").strip()
                match = re.search(r'\{[\s\S]*\}', clean)
                card_data = json.loads(match.group(0) if match else clean)
            except Exception as e:
                return {"error": f"Kartenerkennung fehlgeschlagen: {str(e)}", "raw": raw, "myHand": "Nicht erkennbar", "board": "", "opponents": 1, "winPct": 0, "handStrength": "—", "handName": "Nicht erkennbar", "action": "—", "actionReason": "Karte konnte nicht erkannt werden", "sizing": "", "boardTexture": "", "opponentRanges": "", "analysis": f"Kartenerkennung fehlgeschlagen. Claude Antwort: {raw[:200]}", "whatISee": ""}

            my_hand_str = card_data.get("myHand", "")
            board_str = card_data.get("board", "")
            opponents = int(card_data.get("opponents", 1))

        hole_cards = parse_cards(my_hand_str)
        board_cards = parse_cards(board_str)
        board_stage = get_board_stage(board_cards)

        win_pct = 0
        hand_name = "Nicht erkennbar"
        hand_strength = "—"

        if len(hole_cards) == 2:
            if len(board_cards) == 0:
                win_pct = simulate_win_pct(hole_cards, [], opponents, 2000)
                hand_name = "Preflop Starthand"
                hand_strength = "Stark" if win_pct >= 60 else "Mittel" if win_pct >= 45 else "Schwach"
            elif len(board_cards) >= 3:
                raw_name, hand_strength = get_hand_info(hole_cards, board_cards)
                if raw_name:
                    hand_name = get_pair_type(hole_cards, board_cards, raw_name)
                win_pct = simulate_win_pct(hole_cards, board_cards, opponents, 3000)

        action, action_reason, sizing = recommend_action(win_pct, board_stage, opponents)

        analysis_text = ""
        if len(hole_cards) == 2 and (len(board_cards) == 0 or len(board_cards) >= 3):
            try:
                resp2 = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-opus-4-5",
                        "max_tokens": 500,
                        "messages": [{
                            "role": "user",
                            "content": ANALYSIS_PROMPT.format(
                                myHand=my_hand_str,
                                board=board_str if board_str else "Kein Board (Preflop)",
                                boardStage=board_stage,
                                handName=hand_name,
                                winPct=win_pct,
                                opponents=opponents
                            )
                        }]
                    }
                )
                analysis_text = resp2.json().get("content", [{}])[0].get("text", "")
            except:
                analysis_text = f"{hand_name} — {win_pct}% Gewinnchance gegen {opponents} Gegner."

        return {
            "myHand": my_hand_str,
            "board": board_str,
            "boardStage": board_stage,
            "opponents": opponents,
            "winPct": win_pct,
            "handStrength": hand_strength,
            "handName": hand_name,
            "action": action,
            "actionReason": action_reason,
            "sizing": sizing,
            "boardTexture": "",
            "opponentRanges": "",
            "analysis": analysis_text,
            "whatISee": ""
        }

@app.get("/")
def root():
    return {"status": "Poker AI Backend online"}
