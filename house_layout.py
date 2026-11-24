"""Tidy automatic layout of one family line: a head, partners and descendants.

Blood relatives sit in the main line with partners to their right, and child
lines arrive at the blood relative's portrait. A partner's own parents belong to
that partner's family line, so one view never has to show both sides of every
marriage. No interface code here.
"""
import itertools
import math
from dataclasses import dataclass, field

from model import TreeIndex

PORTRAIT_W, PORTRAIT_H = 116.0, 150.0
LABEL_H = 52.0
COUPLE_GAP = 116.0
SIBLING_GAP = 84.0
ROW_H = 340.0
BUS_OFFSET = 262.0
MAX_GENERATIONS = 150  # Protects against absurdly deep data in imported files.
MAX_ANCESTOR_GENERATIONS = 12  # Each generation doubles, and 4096 cards is already huge.
RAIL_STEP = 22.0


@dataclass(frozen=True)
class Metrics:
    """Every size a layout uses, so card styles can change them all together."""
    card_w: float = PORTRAIT_W
    card_h: float = PORTRAIT_H
    label_h: float = LABEL_H
    couple_gap: float = COUPLE_GAP
    sibling_gap: float = SIBLING_GAP
    row_h: float = ROW_H
    bus_offset: float = BUS_OFFSET
    rail_step: float = RAIL_STEP
    fold_lift: float = 48.0  # A folded ancestor line: its stub rises this far above the card.
    fold_drop: float = 16.0  # A folded descendant line: its button sits this far below the label.
    style: str = "portrait"  # How a card is drawn: portrait, round, compact or names.
    name_px: int = 16
    detail_px: int = 15
    button_h: float = 28.0  # Add buttons and their text.
    button_px: int = 14
    fold_r: float = 11.0  # Fold buttons on the lines.


PORTRAIT = Metrics()
ROUND = Metrics(card_w=100.0, card_h=100.0, label_h=50.0, couple_gap=90.0, sibling_gap=64.0,
                row_h=270.0, bus_offset=208.0, rail_step=18.0, fold_lift=40.0, fold_drop=12.0,
                style="round")
COMPACT = Metrics(card_w=170.0, card_h=56.0, label_h=0.0, couple_gap=50.0, sibling_gap=30.0,
                  row_h=140.0, bus_offset=100.0, rail_step=12.0, fold_lift=34.0, fold_drop=14.0,
                  style="compact", name_px=15, detail_px=13, button_h=24.0, button_px=12, fold_r=10.0)
NAMES = Metrics(card_w=136.0, card_h=28.0, label_h=0.0, couple_gap=44.0, sibling_gap=24.0,
                row_h=92.0, bus_offset=60.0, rail_step=8.0, fold_lift=24.0, fold_drop=12.0,
                style="names", name_px=14, detail_px=12, button_h=20.0, button_px=11, fold_r=9.0)
STYLES = {"portrait": PORTRAIT, "round": ROUND, "compact": COMPACT, "names": NAMES}


@dataclass
class PlacedCard:
    person_id: str
    x: float
    y: float
    blood: bool


@dataclass
class Fold:
    """A place where a branch can be folded away: "up" hides someone's ancestors,
    "down" their descendants, "side" their brothers and sisters with their families
    (folding a level of the tree down onto the direct line). When folded, `count`
    people are hidden. `align` says which edge of the button sits at x: "centre", or
    "right"/"left" for the up and side buttons that share a line."""
    person_id: str
    direction: str
    x: float
    y: float
    folded: bool = False
    count: int = 0
    align: str = "centre"


@dataclass
class HouseLayout:
    root_id: str | None = None
    cards: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    hidden: dict = field(default_factory=dict)
    folds: list = field(default_factory=list)
    metrics: Metrics = PORTRAIT
    wedges: list = field(default_factory=list)  # Only the fan chart uses these instead of cards.

    def bounds(self):
        m = self.metrics
        if not self.cards:
            return 0.0, 0.0, 0.0, 0.0
        return (
            min(c.x for c in self.cards),
            min(c.y for c in self.cards),
            max(c.x for c in self.cards) + m.card_w,
            max(c.y for c in self.cards) + m.card_h + m.label_h,
        )


@dataclass
class _Block:
    cards: list
    lines: list
    left: float
    right: float
    anchor: float
    folds: list = field(default_factory=list)

    def moved(self, dx):
        return _Block(
            [PlacedCard(c.person_id, c.x + dx, c.y, c.blood) for c in self.cards],
            [(x1 + dx, y1, x2 + dx, y2) for x1, y1, x2, y2 in self.lines],
            self.left + dx,
            self.right + dx,
            self.anchor + dx,
            [Fold(f.person_id, f.direction, f.x + dx, f.y, f.folded, f.count, f.align) for f in self.folds],
        )


class _Builder:
    def __init__(self, tree, collapsed, metrics=PORTRAIT):
        self.m = metrics
        self.tree = tree
        self.collapsed = collapsed
        self.index = TreeIndex(tree)
        self.expanded_families = set()
        self.hidden = {}

    def _partner_slots(self, person_id, y):
        """Place partners. The first goes right, the second left, any others further right.

        Keeping the person between two partners stops it looking as if the two
        partners are married to each other. Further partners connect by a line over
        the top of the row, so nobody seems joined to the partner beside them.
        Returns the cards, the lines and each family with the point its child line
        starts from, ordered left to right.
        """
        m = self.m
        middle_y = y + m.card_h / 2
        cards, lines, slots = [], [], []
        left_edge, right_edge = 0.0, m.card_w
        partner_number = 0
        for family in self.index.families_of(person_id):
            partner = next(
                (p for p in family.partners if p != person_id and p in self.tree.people),
                None,
            )
            if partner is None:
                # Starts below the name, so the line doesn't run through the text.
                slots.append((m.card_w / 2, y + m.card_h + m.label_h, family))
                continue
            partner_number += 1
            if partner_number == 2:
                partner_x = left_edge - m.couple_gap - m.card_w
                lines.append((partner_x + m.card_w, middle_y, left_edge, middle_y))
                drop_x = partner_x + m.card_w + m.couple_gap / 2
                left_edge = partner_x
                start_y = middle_y
            elif partner_number == 1:
                partner_x = right_edge + m.couple_gap
                lines.append((right_edge, middle_y, partner_x, middle_y))
                drop_x = partner_x - m.couple_gap / 2
                right_edge = partner_x + m.card_w
                start_y = middle_y
            else:
                partner_x = right_edge + m.couple_gap
                rail_y = y - m.rail_step * (partner_number - 2)
                rail_start = m.card_w / 2 + 14.0 * (partner_number - 2)
                partner_top = partner_x + m.card_w / 2
                lines.append((rail_start, y, rail_start, rail_y))
                lines.append((rail_start, rail_y, partner_top, rail_y))
                lines.append((partner_top, rail_y, partner_top, y))
                drop_x = partner_x - m.couple_gap / 2
                right_edge = partner_x + m.card_w
                start_y = rail_y
            cards.append(PlacedCard(partner, partner_x, y, False))
            slots.append((drop_x, start_y, family))
        slots.sort(key=lambda slot: slot[0])
        return cards, lines, slots, left_edge, right_edge

    def block(self, person_id, row, path):
        m = self.m
        y = row * m.row_h
        partner_cards, lines, slots, left, right = self._partner_slots(person_id, y)
        cards = [PlacedCard(person_id, 0.0, y, True)] + partner_cards
        folds = []

        if person_id in self.collapsed:
            count = self.tree.descendant_count(person_id, self.index)
            if count:
                self.hidden[person_id] = count
                folds.append(Fold(person_id, "down", m.card_w / 2, y + m.card_h + m.label_h + m.fold_drop, True, count))
            slots = []
        elif row >= MAX_GENERATIONS:
            slots = []

        kids_left_limit = None
        bars = []  # (left, right, level) of the bars already drawn under this person.
        for drop_x, drop_y, family in slots:
            if family.id in self.expanded_families:
                continue
            self.expanded_families.add(family.id)
            kids = [
                self.block(child, row + 1, path | {child})
                for child in family.child_ids
                if child in self.tree.people and child not in path
            ]
            if not kids:
                continue

            cursor = 0.0
            placed = []
            for kid in kids:
                placed.append(kid.moved(cursor - kid.left))
                cursor += kid.right - kid.left + m.sibling_gap
            shift = drop_x - (placed[0].anchor + placed[-1].anchor) / 2
            if kids_left_limit is not None:
                shift = max(shift, kids_left_limit - placed[0].left)
            placed = [kid.moved(shift) for kid in placed]

            anchors = [kid.anchor for kid in placed]
            # Each partner's children hang from a bar of their own: a bar that would run
            # along another family's bar goes a step lower, so the drops of the second and
            # third partner do not land on the first one's bar.
            span = (min(anchors + [drop_x]), max(anchors + [drop_x]))
            levels = max(1, int((m.row_h - m.bus_offset) // m.rail_step))
            level = 0
            while level < levels - 1 and any(lv == level and a <= span[1] + m.rail_step and span[0] <= b + m.rail_step
                                             for a, b, lv in bars):
                level += 1
            bars.append((span[0], span[1], level))
            bus_y = y + m.bus_offset + level * m.rail_step
            lines.append((drop_x, drop_y, drop_x, bus_y))
            if not any(f.person_id == person_id for f in folds):
                folds.append(Fold(person_id, "down", drop_x, (drop_y + bus_y) / 2))
            lines.append(
                (min(anchors + [drop_x]), bus_y, max(anchors + [drop_x]), bus_y)
            )
            child_y = (row + 1) * m.row_h
            for kid in placed:
                lines.append((kid.anchor, bus_y, kid.anchor, child_y))
                cards.extend(kid.cards)
                lines.extend(kid.lines)
                folds.extend(kid.folds)
            left = min(left, placed[0].left)
            right = max(right, placed[-1].right)
            kids_left_limit = placed[-1].right + m.sibling_gap

        return _Block(cards, lines, left, right, m.card_w / 2, folds)


def layout_house(tree, root_id, collapsed=frozenset(), metrics=PORTRAIT):
    if root_id not in tree.people:
        return HouseLayout(metrics=metrics)
    builder = _Builder(tree, collapsed, metrics)
    block = builder.block(root_id, 0, frozenset({root_id}))
    return HouseLayout(root_id, block.cards, block.lines, builder.hidden, block.folds, metrics)


class _AncestorBuilder:
    def __init__(self, tree, max_rows=MAX_ANCESTOR_GENERATIONS, folded=frozenset(), siblings=False,
                 metrics=PORTRAIT, side_folded=frozenset()):
        self.side_folded = side_folded  # People whose brothers and sisters are folded away.
        self.m = metrics
        self.tree = tree
        self.index = TreeIndex(tree)
        self.max_rows = max_rows
        self.folded = folded
        self.siblings = siblings  # Also show each ancestor's brothers and sisters.
        self.sibling_row = 1  # From which generation up brothers and sisters are drawn here.
        self.placed = set()  # Everyone already drawn, so nobody is drawn twice.
        self.skip_card = set()  # People whose card the caller draws itself.
        self.no_drop = set()  # People whose line down from their parents the caller draws.

    def ancestor_count(self, person_id):
        seen, waiting = set(), [person_id]
        while waiting:
            family = self.index.birth_family_of(waiting.pop())
            for parent in family.partners if family else []:
                if parent not in seen and parent in self.tree.people:
                    seen.add(parent)
                    waiting.append(parent)
        return len(seen - {person_id})

    def block(self, person_id, row, path, side="left"):
        """`side` says where brothers and sisters go: away from the partner beside them."""
        m = self.m
        y = -row * m.row_h
        family = self.index.birth_family_of(person_id)
        parents = [
            p for p in (family.partners if family else []) if p in self.tree.people and p not in path
        ][:2]
        if parents and person_id in self.folded:
            count = self.ancestor_count(person_id)
            if self.siblings and row >= 1:
                count += len([c for c in family.child_ids if c != person_id and c in self.tree.people])
            fold = Fold(person_id, "up", m.card_w / 2, y - m.fold_lift - 12, True, count)
            stub = [(m.card_w / 2, y - m.fold_lift, m.card_w / 2, y)]
            return _Block([PlacedCard(person_id, 0.0, y, True)], stub, 0.0, m.card_w, m.card_w / 2, [fold])
        if not parents and family is not None and self.siblings and row >= self.sibling_row:
            brothers = [c for c in family.child_ids
                        if c != person_id and c in self.tree.people and c not in path and c not in self.placed]
            if brothers:
                self.placed.update(brothers)
                step = m.card_w + m.sibling_gap
                cards = [PlacedCard(person_id, 0.0, y, True)]
                anchors, left, right = [m.card_w / 2], 0.0, m.card_w
                for number, brother in enumerate(brothers, start=1):
                    x = (-step if side == "left" else step) * number
                    cards.append(PlacedCard(brother, x, y, True))
                    anchors.append(x + m.card_w / 2)
                    left, right = min(left, x), max(right, x + m.card_w)
                return _Block(cards, _sibling_bar(anchors, y, m), left, right, m.card_w / 2)
        if not parents or row >= self.max_rows:
            return _Block([PlacedCard(person_id, 0.0, y, True)], [], 0.0, m.card_w, m.card_w / 2)

        parent_y = -(row + 1) * m.row_h
        first = self.block(parents[0], row + 1, path | {parents[0]}, "left")
        first = first.moved(-first.left)
        cards, lines, folds = list(first.cards), list(first.lines), list(first.folds)
        left, right = first.left, first.right
        if len(parents) == 2:
            second = self.block(parents[1], row + 1, path | {parents[1]}, "right")
            second = second.moved(right + m.couple_gap - second.left)
            cards += second.cards
            lines += second.lines
            folds += second.folds
            right = second.right
            middle_y = parent_y + m.card_h / 2
            lines.append(
                (first.anchor + m.card_w / 2, middle_y, second.anchor - m.card_w / 2, middle_y)
            )
            drop_x, drop_y = (first.anchor + second.anchor) / 2, middle_y
        else:
            drop_x, drop_y = first.anchor, parent_y + m.card_h + m.label_h
        if person_id not in self.skip_card:
            cards.append(PlacedCard(person_id, drop_x - m.card_w / 2, y, True))
        brothers = [
            c for c in family.child_ids
            if c != person_id and c in self.tree.people and c not in path and c not in self.placed
        ] if self.siblings and row >= self.sibling_row else []
        self.placed.update(brothers)
        if brothers and person_id in self.side_folded:
            if person_id not in self.no_drop:
                lines.append((drop_x, drop_y, drop_x, y))
                fold_y = (drop_y + y) / 2
                folds.append(Fold(person_id, "up", drop_x - 3, fold_y, align="right"))
                folds.append(Fold(person_id, "side", drop_x + 3, fold_y, True, len(brothers), "left"))
            return _Block(cards, lines, left, right, drop_x, folds)
        if not brothers:
            if person_id not in self.no_drop:
                lines.append((drop_x, drop_y, drop_x, y))
                folds.append(Fold(person_id, "up", drop_x, (drop_y + y) / 2))
            return _Block(cards, lines, left, right, drop_x, folds)

        # Aunts and uncles sit on the outer side, so the couple below stays together.
        step = m.card_w + m.sibling_gap
        anchors = [drop_x]
        for number, brother in enumerate(brothers, start=1):
            x = drop_x - m.card_w / 2 + (-step if side == "left" else step) * number
            cards.append(PlacedCard(brother, x, y, True))
            anchors.append(x + m.card_w / 2)
            left, right = min(left, x), max(right, x + m.card_w)
        bus_y = y - m.row_h + m.bus_offset
        lines.append((drop_x, drop_y, drop_x, bus_y))
        lines.append((min(anchors), bus_y, max(anchors), bus_y))
        for anchor in anchors:
            lines.append((anchor, bus_y, anchor, y))
        folds += _fold_pair(person_id, drop_x, (drop_y + bus_y) / 2)
        return _Block(cards, lines, left, right, drop_x, folds)


def layout_ancestors(tree, person_id, folded=frozenset(), metrics=PORTRAIT):
    """Someone at the bottom, with both parents above them, and so on upward."""
    if person_id not in tree.people:
        return HouseLayout(metrics=metrics)
    block = _AncestorBuilder(tree, folded=folded, metrics=metrics).block(person_id, 0, frozenset({person_id}))
    return HouseLayout(person_id, block.cards, block.lines, folds=block.folds, metrics=metrics)


FAMILY_GENERATIONS_UP = 3


def _bands(cards, lines, m):
    """For each row, the leftmost and rightmost x in use, counting the lines into that row."""
    bands = {}

    def use(row_y, a, b):
        low, high = bands.get(row_y, (a, b))
        bands[row_y] = (min(low, a), max(high, b))

    for card in cards:
        use(round(card.y), card.x, card.x + m.card_w)
    for x1, y1, x2, y2 in lines:
        if y1 == y2 and x1 != x2:
            use(round(math.ceil(y1 / m.row_h - 1e-9) * m.row_h), min(x1, x2), max(x1, x2))
    return bands


def _beside(fixed_cards, fixed_lines, block, side, m):
    """How far to move `block` so it sits clear of everything fixed, row by row, on one side."""
    fixed = _bands(fixed_cards, fixed_lines, m)
    mine = _bands(block.cards, block.lines, m)
    shifts = []
    for row_y, (low, high) in mine.items():
        if row_y in fixed:
            fixed_low, fixed_high = fixed[row_y]
            if side == "left":
                shifts.append(fixed_low - m.sibling_gap - high)
            else:
                shifts.append(fixed_high + m.sibling_gap - low)
    if not shifts:
        return 0.0
    return min(shifts) if side == "left" else max(shifts)


def _drop_from(cards, parents, parent_y, m):
    """Where the line down to a couple's children starts."""
    by_person = {}
    for c in cards:
        if c.person_id in parents and c.y == parent_y:
            by_person.setdefault(c.person_id, []).append(c.x + m.card_w / 2)
    # Someone drawn twice in the row (cousins who married: the shared grandparents' child
    # appears on both sides) must not stretch the drop to their far copy: use the copies
    # that stand closest together, the couple as drawn side by side.
    xs = []
    for options in itertools.product(*by_person.values()):
        if not xs or max(options) - min(options) < xs[-1] - xs[0]:
            xs = sorted(options)
    if len(xs) >= 2:
        return (xs[0] + xs[-1]) / 2, parent_y + m.card_h / 2
    if xs:
        return xs[0], parent_y + m.card_h + m.label_h
    return None


def _sibling_bar(anchors, child_y, m):
    """Brothers and sisters whose parents are not known: a bar over them, joined to nobody."""
    if len(anchors) < 2:
        return []
    bar_y = child_y - m.row_h + m.bus_offset
    return [(min(anchors), bar_y, max(anchors), bar_y)] + [(a, bar_y, a, child_y) for a in anchors]


def _fold_pair(person_id, x, y):
    """The two buttons on a line from someone's parents when they have brothers and
    sisters: up folds everything above away, down folds this level's side branches
    onto the direct line."""
    return [Fold(person_id, "up", x - 3, y, align="right"), Fold(person_id, "side", x + 3, y, align="left")]


def _children_lines(drop, anchors, child_y, m):
    drop_x, drop_y = drop
    bus_y = child_y - m.row_h + m.bus_offset
    lines = [(drop_x, drop_y, drop_x, bus_y), (min(anchors + [drop_x]), bus_y, max(anchors + [drop_x]), bus_y)]
    lines += [(anchor, bus_y, anchor, child_y) for anchor in anchors]
    return lines, (drop_y + bus_y) / 2


def layout_family(tree, focus_id, collapsed=frozenset(), generations_up=FAMILY_GENERATIONS_UP,
                  folded=frozenset(), metrics=PORTRAIT, side_folded=frozenset()):
    """Everyone around one person, the way family tree programs show a whole family.

    Above: the direct ancestors, with their brothers and sisters from the
    grandparents up. Around the person: their brothers and sisters, and their
    parents' brothers and sisters, each with partners and all descendants, so
    cousins and their children appear too. Below: the person's own partners and
    descendants. Each family group is packed row by row against what is already
    placed, so nothing overlaps and no line runs through a card.
    """
    m = metrics
    if focus_id not in tree.people:
        return HouseLayout(metrics=m)
    index = TreeIndex(tree)
    down = _Builder(tree, collapsed, m)  # Shared, so a family is only ever drawn once.

    below = down.block(focus_id, 0, frozenset({focus_id}))
    cards, lines, folds = list(below.cards), list(below.lines), list(below.folds)
    family = index.birth_family_of(focus_id)
    parents = [p for p in (family.partners if family else []) if p in tree.people][:2]
    if family is not None and not parents:
        # Brothers and sisters known, parents not: they stand together under a bar.
        anchors = [below.anchor]
        for sibling in [c for c in family.child_ids if c != focus_id and c in tree.people]:
            block = down.block(sibling, 0, frozenset({sibling}))
            block = block.moved(_beside(cards, lines, block, "left", m))
            cards += block.cards
            lines += block.lines
            folds += block.folds
            anchors.append(block.anchor)
        lines += _sibling_bar(anchors, 0.0, m)
        return HouseLayout(focus_id, cards, lines, down.hidden, folds, m)
    if not parents or generations_up < 1:
        return HouseLayout(focus_id, cards, lines, down.hidden, folds, m)

    drawn = {card.person_id for card in cards}
    siblings = [c for c in family.child_ids if c != focus_id and c in tree.people and c not in drawn]
    if focus_id in folded:
        # Parents, brothers and sisters and everything above fold away together.
        count = _AncestorBuilder(tree).ancestor_count(focus_id)
        count += sum(len(_Builder(tree, collapsed, m).block(s, 0, frozenset({s})).cards) for s in siblings)
        lines.append((below.anchor, -m.fold_lift, below.anchor, 0.0))
        folds.append(Fold(focus_id, "up", below.anchor, -m.fold_lift - 12, True, count))
        return HouseLayout(focus_id, cards, lines, down.hidden, folds, m)

    side_count = 0
    if focus_id in side_folded and siblings:
        side_count = sum(len(_Builder(tree, collapsed, m).block(s, 0, frozenset({s})).cards) for s in siblings)
        siblings = []
    # Brothers and sisters, each with their own family, to the left.
    anchors = [below.anchor]
    for sibling in siblings:
        block = down.block(sibling, 0, frozenset({sibling}))
        block = block.moved(_beside(cards, lines, block, "left", m))
        cards += block.cards
        lines += block.lines
        folds += block.folds
        anchors.append(block.anchor)

    # The direct ancestors. The parents' lines down are drawn here, to include their siblings.
    up = _AncestorBuilder(tree, generations_up, folded, siblings=True, metrics=m, side_folded=side_folded)
    up.sibling_row = 2
    up.placed = {card.person_id for card in cards}
    up.skip_card = {focus_id}
    up.no_drop = {focus_id} | set(parents)
    above = up.block(focus_id, 0, frozenset({focus_id}))
    above = above.moved((min(anchors) + max(anchors)) / 2 - above.anchor)
    cards += above.cards
    lines += above.lines
    folds += above.folds

    drop = _drop_from(cards, parents, -m.row_h, m)
    new_lines, fold_y = _children_lines(drop, anchors, 0.0, m)
    lines += new_lines
    if side_count:
        folds.append(Fold(focus_id, "up", drop[0] - 3, fold_y, align="right"))
        folds.append(Fold(focus_id, "side", drop[0] + 3, fold_y, True, side_count, "left"))
    elif siblings:
        folds += _fold_pair(focus_id, drop[0], fold_y)
    else:
        folds.append(Fold(focus_id, "up", drop[0], fold_y))

    # Aunts and uncles with their families: the father's side left, the mother's right.
    for parent, side in zip(parents, ("left", "right")):
        parent_family = index.birth_family_of(parent)
        grandparents = [p for p in (parent_family.partners if parent_family else []) if p in tree.people]
        if parent_family is None or (grandparents and generations_up < 2):
            continue
        shown = {card.person_id for card in cards}
        aunts = [c for c in parent_family.child_ids if c != parent and c in tree.people and c not in shown]
        if parent in folded:
            # The folded count already has the aunts and uncles; add their partners and families.
            extra = sum(len(_Builder(tree, collapsed, m).block(a, -1, frozenset({a})).cards) - 1 for a in aunts)
            for fold in folds:
                if fold.person_id == parent and fold.folded:
                    fold.count += extra
            continue
        aunts_hidden = 0
        if parent in side_folded and aunts and grandparents:
            aunts_hidden = sum(len(_Builder(tree, collapsed, m).block(a, -1, frozenset({a})).cards) for a in aunts)
            had_aunts, aunts = True, []
        else:
            had_aunts = bool(aunts)
        parent_card = next(c for c in cards if c.person_id == parent and c.y == -m.row_h)
        parent_anchors = [parent_card.x + m.card_w / 2]
        for aunt in aunts:
            block = down.block(aunt, -1, frozenset({aunt}))
            block = block.moved(_beside(cards, lines, block, side, m))
            cards += block.cards
            lines += block.lines
            folds += block.folds
            parent_anchors.append(block.anchor)
        drop = _drop_from(cards, grandparents, -2 * m.row_h, m) if grandparents else None
        if drop is None:
            lines += _sibling_bar(parent_anchors, -m.row_h, m)
            continue
        new_lines, fold_y = _children_lines(drop, parent_anchors, -m.row_h, m)
        lines += new_lines
        if aunts_hidden:
            folds.append(Fold(parent, "up", drop[0] - 3, fold_y, align="right"))
            folds.append(Fold(parent, "side", drop[0] + 3, fold_y, True, aunts_hidden, "left"))
        elif had_aunts:
            folds += _fold_pair(parent, drop[0], fold_y)
        else:
            folds.append(Fold(parent, "up", drop[0], fold_y))
    return HouseLayout(focus_id, cards, lines, down.hidden, folds, m)


def layout_bowtie(tree, focus_id, generations=4, metrics=PORTRAIT):
    """A sideways pedigree: the father's ancestors to the left, the mother's to the right.

    Each column is one generation. Every person sits in the middle of the rows
    their own ancestors take up, so lines run only through the gaps.
    """
    m = metrics
    if focus_id not in tree.people:
        return HouseLayout(metrics=m)
    index = TreeIndex(tree)
    column = m.card_w + max(m.couple_gap, 60.0) * 1.4
    slot = m.card_h + m.label_h + max(m.sibling_gap, 16.0) * 0.6
    cards, lines = [], []

    def parents_of(person_id, path):
        family = index.birth_family_of(person_id)
        return [p for p in (family.partners if family else []) if p in tree.people and p not in path][:2]

    def rows_needed(person_id, depth, path):
        parents = parents_of(person_id, path) if depth < generations else []
        return max(1, sum(rows_needed(p, depth + 1, path | {p}) for p in parents))

    def place(person_id, depth, top, direction, path):
        """Place someone and their ancestors from row `top`; returns the card's centre."""
        parents = parents_of(person_id, path) if depth < generations else []
        height = rows_needed(person_id, depth, path)
        y = top * slot + (height * slot - slot) / 2
        x = direction * depth * column - m.card_w / 2
        cards.append(PlacedCard(person_id, x, y, True))
        centre = (x + m.card_w / 2, y + m.card_h / 2)
        row = top
        for parent in parents:
            px, py = place(parent, depth + 1, row, direction, path | {parent})
            # An elbow through the gap between the two columns.
            near = x if direction < 0 else x + m.card_w
            far = px + m.card_w / 2 if direction < 0 else px - m.card_w / 2
            middle = (near + far) / 2
            lines.extend([(near, centre[1], middle, centre[1]), (middle, centre[1], middle, py),
                          (middle, py, far, py)])
            row += rows_needed(parent, depth + 1, path | {parent})
        return centre

    cards.append(PlacedCard(focus_id, -m.card_w / 2, 0.0, True))
    focus_mid = m.card_h / 2
    parents = parents_of(focus_id, {focus_id})
    for parent, direction in zip(parents, (-1, 1)):
        height = rows_needed(parent, 1, {focus_id, parent})
        top = -(height - 1) / 2  # Each side is centred on the person in the middle.
        px, py = place(parent, 1, top, direction, {focus_id, parent})
        near = (m.card_w / 2) * direction
        far = px - m.card_w / 2 * direction
        middle = (near + far) / 2
        lines += [(near, focus_mid, middle, focus_mid), (middle, focus_mid, middle, py), (middle, py, far, py)]
    return HouseLayout(focus_id, cards, lines, metrics=m)


@dataclass
class Wedge:
    """One person's place in a fan chart: a ring segment around the centre."""
    person_id: str
    generation: int
    start: float  # Degrees, counter-clockwise from three o'clock, as Qt draws arcs.
    span: float


FAN_CENTRE_R = 95.0
FAN_RING = 105.0


def layout_fan(tree, focus_id, generations=4, metrics=PORTRAIT):
    """A half circle of ancestors: one ring per generation, the father's side on the left."""
    layout = HouseLayout(focus_id, metrics=metrics)
    if focus_id not in tree.people:
        return layout
    index = TreeIndex(tree)
    layout.wedges = [Wedge(focus_id, 0, 0.0, 180.0)]

    def walk(person_id, generation, slot, path):
        if generation > generations:
            return
        family = index.birth_family_of(person_id)
        parents = [p for p in (family.partners if family else []) if p in tree.people][:2]
        span = 180.0 / (2 ** generation)
        for number, parent in enumerate(parents):
            if parent in path:
                continue
            child_slot = slot * 2 + number
            start = 180.0 - (child_slot + 1) * span  # Father first, from the left.
            layout.wedges.append(Wedge(parent, generation, start, span))
            walk(parent, generation + 1, child_slot, path | {parent})

    walk(focus_id, 1, 0, {focus_id})
    return layout
