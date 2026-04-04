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
        # Return only hand name, strength will be determined by win%
        return hand_name, None
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

def detect_draws(hole_cards, board_cards):
    """Detect flush draws and straight draws including nut flush draw"""
    all_cards = hole_cards + board_cards
    draws = []
    suit_names = {'s':'♠', 'h':'♥', 'd':'♦', 'c':'♣'}
    rank_chars = "23456789TJQKA"

    # Count suits for all cards
    suit_counts = {'s':[],'h':[],'d':[],'c':[]}
    for c in all_cards:
        cs = Card.int_to_str(c)[-1]
        rank = Card.get_rank_int(c)
        if cs in suit_counts:
            suit_counts[cs].append(rank)

    for s, ranks in suit_counts.items():
        if len(ranks) == 4:
            # Check if it's Nut Flush Draw
            # Nut = highest possible flush card is in my hand or board already covered
            hole_suit_ranks = []
            for c in hole_cards:
                if Card.int_to_str(c)[-1] == s:
                    hole_suit_ranks.append(Card.get_rank_int(c))
            board_suit_ranks = []
            for c in board_cards:
                if Card.int_to_str(c)[-1] == s:
                    board_suit_ranks.append(Card.get_rank_int(c))

            all_suit_ranks = sorted(ranks, reverse=True)
            # Ace = rank 12
            ace_rank = 12
            king_rank = 11

            # Nut flush draw = I have the highest possible flush card
            # If Ace is in my hand → Nut
            # If Ace is on board and King is in my hand → Nut (ace belongs to flush too)
            is_nut = False
            if ace_rank in hole_suit_ranks:
                is_nut = True
            elif ace_rank in board_suit_ranks and king_rank in hole_suit_ranks:
                is_nut = True
            elif ace_rank in board_suit_ranks and king_rank in board_suit_ranks:
                # Next highest in hand?
                remaining = [r for r in range(11, -1, -1) if r not in board_suit_ranks]
                if remaining and hole_suit_ranks and max(hole_suit_ranks) == remaining[0]:
                    is_nut = True

            my_highest = rank_chars[max(hole_suit_ranks)] if hole_suit_ranks else '?'
            suit_sym = suit_names.get(s, s)

            if is_nut:
                draws.append(f"Nut Flush Draw ({suit_sym})")
            else:
                draws.append(f"Flush Draw ({my_highest}{suit_sym})")

    # Straight draws
    vals = sorted(set([Card.get_rank_int(c) for c in all_cards]))
    if 12 in vals:
        vals_with_low_ace = [-1] + vals
    else:
        vals_with_low_ace = vals

    for val_list in [vals, vals_with_low_ace]:
        consec = 1
        max_consec = 1
        for i in range(1, len(val_list)):
            if val_list[i] == val_list[i-1] + 1:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 1
        if max_consec >= 4:
            draws.append("OESD (Open Ended Straight Draw)")
            break
        elif max_consec == 3 and "Gutshot" not in str(draws):
            draws.append("Gutshot Straight Draw")

    return list(dict.fromkeys(draws))  # remove duplicates

def get_flush_name(hole_cards, board_cards):
    """Get correct flush name based on highest card in flush"""
    rank_chars = "23456789TJQKA"
    rank_names = {'2':'Zwei','3':'Drei','4':'Vier','5':'Fünf','6':'Sechs',
                  '7':'Sieben','8':'Acht','9':'Neun','T':'Zehn',
                  'J':'Bube','Q':'Dame','K':'König','A':'Ass'}
    suit_names = {'s':'♠','h':'♥','d':'♦','c':'♣'}

    all_cards = hole_cards + board_cards
    suit_counts = {'s':[],'h':[],'d':[],'c':[]}
    for c in all_cards:
        cs = Card.int_to_str(c)[-1]
        rank = Card.get_rank_int(c)
        if cs in suit_counts:
            suit_counts[cs].append((rank, c))

    for s, rank_cards in suit_counts.items():
        if len(rank_cards) >= 5:
            best5 = sorted(rank_cards, key=lambda x: x[0], reverse=True)[:5]
            highest_rank = best5[0][0]
            highest_char = rank_chars[highest_rank]
            return f"{rank_names.get(highest_char, highest_char)}-High Flush ({suit_names.get(s,s)})"
    return "Flush"

def generate_analysis(hand_name, hand_strength, win_pct, opponents, board_stage, my_hand_str, board_str):
    """Generate clean analysis text based on win% - always consistent"""

    # Hand description
    if "Royal Flush" in hand_name:
        hand_desc = f"Du hast einen Royal Flush — die bestmögliche Hand überhaupt!"
    elif "Straight Flush" in hand_name:
        hand_desc = f"Du hast einen Straight Flush — fast unschlagbar."
    elif "Four of a Kind" in hand_name:
        hand_desc = f"Du hast Four of a Kind — extrem starke Hand."
    elif "Full House" in hand_name:
        hand_desc = f"Du hast ein Full House."
    elif "Flush" in hand_name and "Draw" not in hand_name:
        hand_desc = f"Du hast einen {hand_name}."
    elif "Straight" in hand_name and "Draw" not in hand_name:
        hand_desc = f"Du hast eine Straße."
    elif "Three of a Kind" in hand_name:
        hand_desc = f"Du hast einen Drilling."
    elif "Two Pair" in hand_name:
        hand_desc = f"Du hast Two Pair."
    elif "Overpair" in hand_name:
        hand_desc = f"Du hast ein Overpair — dein Pocket Pair schlägt alle Board-Karten."
    elif "Top Pair" in hand_name:
        hand_desc = f"Du hast Top Pair."
    elif "Middle Pair" in hand_name:
        hand_desc = f"Du hast Middle Pair."
    elif "Bottom Pair" in hand_name:
        hand_desc = f"Du hast Bottom Pair."
    elif "Nut Flush Draw" in hand_name:
        hand_desc = f"Du hast den Nut Flush Draw — beste mögliche Flush Draw."
    elif "Flush Draw" in hand_name:
        hand_desc = f"Du hast einen {hand_name}."
    elif "OESD" in hand_name:
        hand_desc = f"Du hast einen Open Ended Straight Draw — 8 Outs."
    elif "Gutshot" in hand_name:
        hand_desc = f"Du hast einen Gutshot Straight Draw — 4 Outs."
    else:
        hand_desc = f"Du hast {hand_name}."

    # Win% based assessment
    if win_pct >= 90:
        assessment = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner bist du klarer Favorit — raise für maximalen Value."
    elif win_pct >= 75:
        assessment = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner hast du eine starke Hand — raise für Value."
    elif win_pct >= 60:
        assessment = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner bist du Favorit — raise oder call."
    elif win_pct >= 45:
        assessment = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner ist die Situation ausgeglichen — call oder check."
    elif win_pct >= 30:
        assessment = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner bist du Außenseiter — check oder fold."
    else:
        assessment = f"Mit nur {win_pct}% Gewinnchance gegen {opponents} Gegner ist die Hand zu schwach — fold empfohlen."

    # Board stage
    if board_stage == "Preflop":
        stage_info = "Preflop."
    elif board_stage == "Flop":
        stage_info = "Noch Turn und River kommen."
    elif board_stage == "Turn":
        stage_info = "Noch eine Karte — der River."
    elif board_stage == "River":
        stage_info = "Alle Karten liegen — finale Hand."
    else:
        stage_info = ""

    return f"{hand_desc} {assessment} {stage_info}".strip()

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
    async with httpx.AsyncClient(timeout=90) as client:

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
            resp_data = resp.json()
            raw = resp_data.get("content", [{}])[0].get("text", "") if resp_data.get("content") else ""
            if not raw:
                raw_err = json.dumps(resp_data)
                return {"error": f"Leere Antwort von Claude: {raw_err[:200]}", "myHand": "Nicht erkennbar", "board": "", "opponents": 1, "winPct": 0, "handStrength": "—", "handName": "Nicht erkennbar", "action": "—", "actionReason": "Bitte nochmal versuchen", "sizing": "", "boardTexture": "", "opponentRanges": "", "analysis": "Fehler: Leere Antwort. Bitte nochmal fotografieren.", "whatISee": ""}
            try:
                clean = raw.replace("```json","").replace("```","").strip()
                match = re.search(r'\{[\s\S]*\}', clean)
                card_data = json.loads(match.group(0) if match else clean)
            except:
                return {"error": "Kartenerkennung fehlgeschlagen", "raw": raw}

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
                    if raw_name in ["Royal Flush", "Straight Flush"]:
                        hand_name = raw_name
                    elif raw_name == "Flush":
                        hand_name = get_flush_name(hole_cards, board_cards)
                    elif raw_name == "Pair":
                        hand_name = get_pair_type(hole_cards, board_cards, raw_name)
                    else:
                        hand_name = raw_name
                # Add draw detection for weak hands
                if raw_name in ["High Card", "Pair"] or raw_name is None:
                    draws = detect_draws(hole_cards, board_cards)
                    if draws:
                        hand_name = " + ".join(draws) + (f" + {hand_name}" if raw_name and raw_name != "High Card" else "")
                        hand_strength = "Mittel"
                win_pct = simulate_win_pct(hole_cards, board_cards, opponents, 3000)
                hand_strength = win_pct_to_strength(win_pct)

        action, action_reason, sizing = recommend_action(win_pct, board_stage, opponents)

        analysis_text = generate_analysis(hand_name, hand_strength, win_pct, opponents, board_stage, my_hand_str, board_str)

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
            "sizing": "",
            "boardTexture": "",
            "opponentRanges": "",
            "analysis": analysis_text,
            "whatISee": ""
        }

@app.get("/")
def root():
    return {"status": "Poker AI Backend online"}
