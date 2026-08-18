from abc import ABC, abstractmethod

# (my_move, opp_move) -> (my_points, opp_points)
"""
You and a partner pulled off a big bank heist.
You've got the loot sitting in your safehouse,
where you're planning to meet tomorrow to split it.
You could try to BETRAY your partner and take it all
or HONOR your deal and split it evenly. Your partner
can do the same. If you both HONOR the deal, you
both make $3mil. If one of you BETRAYS the other,
the BETRAYING player makes $5mil (can't carry it all)
and the HONORABLE player arrives at the safehouse
to find it empty. If both of you BETRAY, you have
a scuffle and you alert the police, meaning you
can only run off with $1mil each.
"""
PAYOFFS = {
    ("H", "H"): (3, 3),
    ("H", "B"): (0, 5),
    ("B", "H"): (5, 0),
    ("B", "B"): (1, 1),
}


class HeistPlayer(ABC):
    """Abstract base class every Heist bot must extend."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def decide(self, my_history: list[str], opp_history: list[str]) -> str:
        """Return 'H' for 'honor' or 'B' for 'betray'.

        Both history lists are same-length, oldest first, and reflect
        only this match so far.
        """
        raise NotImplementedError

    def __repr__(self):
        return self.name

class CharBot(HeistPlayer):
  def decide(self, mHistory, oHistory):
    bot_type = 0 # 0 for trustful bot, 1 for untrustful
    count = 0
    me = 0
    for item in oHistory:
      if item == "B":
        count += 1
    if len(oHistory) > 0 and float(count) / len(oHistory) >= 0.33:
      bot_type = 1
    count = 0
    for item in mHistory:
      if item =="B":
        count += 1
    if len(mHistory) > 0 and float(count) / len(mHistory) >= 0.5:
      me = 1
    else:
      me = 0
    if bot_type == 0 and me == 0:
      return "H"
    if bot_type == 1 and me == 0:
      return "B"
    if bot_type == 0 and me == 1:
      return "B"
    if bot_type == 1 and me == 1:
      return "B"

class AlwaysBetrayal(HeistPlayer):
    def decide(self, my_history, opp_history):
        return "B"

class TitForTat(HeistPlayer):
    def decide(self, my_history, opp_history):
        if not opp_history:
            return "H"
        return opp_history[-1]

class WinStayLoseShift(HeistPlayer):
    def decide(self, my_history, opp_history):
        if not my_history:
            return "H"
        last_payoff = PAYOFFS[(my_history[-1], opp_history[-1])][0]
        if last_payoff >= 3:  # 3 (mutual honor) or 5 (betrayed them) counts as a "win"
            return my_history[-1]
        return "B" if my_history[-1] == "H" else "H"

def play_match(p1, p2, rounds: int = 200):
    h1, h2 = [], []
    score1 = score2 = 0

    for _ in range(rounds):
        m1 = p1.decide(h1, h2)
        m2 = p2.decide(h2, h1)
        if m1 not in ("H", "B") or m2 not in ("H", "B"):
            raise ValueError(f"Invalid move: {m1!r} or {m2!r}")

        s1, s2 = PAYOFFS[(m1, m2)]
        score1 += s1
        score2 += s2

        h1.append(m1)
        h2.append(m2)

    return score1, score2

if __name__ == "__main__":
  # code placed here runs when the file is run.
  bots = [CharBot("CharBot"), AlwaysBetrayal("AlwaysBetrayal"),
          TitForTat("TitForTat"), WinStayLoseShift("WinStayLoseShift")]
  for i, p1 in enumerate(bots):
    for p2 in bots[i + 1:]:
      print(p1, "vs", p2, "->", play_match(p1, p2))
