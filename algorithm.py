from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
import random
import re
import numpy as np
import pandas as pd


def _natural_sort_key(s: str) -> List:
    """Sort key that orders embedded numbers numerically (e.g. 'Box2' < 'Box10',
    and plain integer names like '1', '2', '10' sort as expected)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", s)]

PLATE_ROWS: List[str] = list("ABCDEFGH")
QC_COLS: List[int] = [1, 2]
SAMPLE_COLS: List[int] = list(range(3, 13))
ALL_COLS: List[int] = list(range(1, 13))

# Column 1 is always fully booked: Blank, PBS x3, then Cal1-4 (top to bottom).
# Column 2 is booked for rows A-F (Cal5-7, then QC1-3); rows G and H are free —
# genuine sample wells, not calibrators.
BIOCRATES_QC_LABELS: Dict[Tuple[str, int], str] = {
    ("A", 1): "Blank", ("B", 1): "PBS",  ("C", 1): "PBS",  ("D", 1): "PBS",
    ("E", 1): "Cal1",  ("F", 1): "Cal2", ("G", 1): "Cal3", ("H", 1): "Cal4",
    ("A", 2): "Cal5",  ("B", 2): "Cal6", ("C", 2): "Cal7",
    ("D", 2): "QC1",   ("E", 2): "QC2",  ("F", 2): "QC3",
    # G2, H2 intentionally absent from this map -> they're free sample wells.
}

# Column 2's free rows (G, H) count as extra sample wells alongside cols 3-12.
_COL2_FREE_POSITIONS: List[Tuple[str, int]] = [("G", 2), ("H", 2)]

# Extra QC2 replicates booked at fixed positions inside the normal sample area —
# always reserved, never available for sample placement, regardless of capacity.
EXTRA_RESERVED_LABELS: Dict[Tuple[str, int], str] = {
    ("A", 6): "QC2", ("C", 9): "QC2", ("E", 12): "QC2",
}

# Column-major candidate sample positions, in true physical loading order: column
# 2's two free rows (G, H) first — they sit immediately left of column 3 on the
# real plate — then cols 3-12 (80). Of these, the 3 EXTRA_RESERVED_LABELS
# positions are always booked, so the true maximum usable capacity is
# MAX_SAMPLE_CAPACITY (79), not len(SAMPLE_POSITIONS).
SAMPLE_POSITIONS: List[Tuple[str, int]] = (
    _COL2_FREE_POSITIONS + [(row, col) for col in SAMPLE_COLS for row in PLATE_ROWS]
)
MAX_SAMPLE_CAPACITY: int = len(SAMPLE_POSITIONS) - len(EXTRA_RESERVED_LABELS)


@dataclass
class Sample:
    sample_id: str
    study_id: str
    repeat_pair: Optional[str] = None
    factor_1: Optional[str] = None
    factor_2: Optional[str] = None
    material: Optional[str] = None
    sample_description: Optional[str] = None
    box_id: Optional[str] = None
    sample_alias: Optional[str] = None


@dataclass
class WellAssignment:
    row: str
    col: int
    sample_id: Optional[str] = None
    study_id: Optional[str] = None
    # 'empty' | 'sample' | 'calibrator'
    well_type: str = "empty"
    repeat_pair: Optional[str] = None
    label: Optional[str] = None  # Std7, QC1, etc.
    factor_1: Optional[str] = None
    factor_2: Optional[str] = None
    material: Optional[str] = None
    sample_description: Optional[str] = None
    box_id: Optional[str] = None
    sample_alias: Optional[str] = None


@dataclass
class Plate:
    plate_number: int
    wells: Dict[Tuple[str, int], WellAssignment] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for row in PLATE_ROWS:
            for col in QC_COLS:
                pos = (row, col)
                if pos in BIOCRATES_QC_LABELS:
                    self.wells[pos] = WellAssignment(
                        row=row, col=col,
                        well_type="calibrator",
                        label=BIOCRATES_QC_LABELS[pos],
                    )
                else:
                    # Column 2's free rows (G, H) — genuine sample wells.
                    self.wells[pos] = WellAssignment(row=row, col=col, well_type="empty")
            for col in SAMPLE_COLS:
                pos = (row, col)
                if pos in EXTRA_RESERVED_LABELS:
                    self.wells[pos] = WellAssignment(
                        row=row, col=col,
                        well_type="calibrator",
                        label=EXTRA_RESERVED_LABELS[pos],
                    )
                else:
                    self.wells[pos] = WellAssignment(row=row, col=col, well_type="empty")

    def available_positions(self) -> List[Tuple[str, int]]:
        return [p for p in SAMPLE_POSITIONS if self.wells[p].well_type == "empty"]

    def n_available(self) -> int:
        return len(self.available_positions())

    def n_sample(self) -> int:
        return sum(1 for w in self.wells.values() if w.well_type == "sample")

    def capacity_remaining(self, capacity: int) -> int:
        """Remaining slots under a configured plate_capacity (<= physical n_available)."""
        return capacity - self.n_sample()

    def assign_sample(self, pos: Tuple[str, int], sample: Sample) -> None:
        self.wells[pos] = WellAssignment(
            row=pos[0], col=pos[1],
            sample_id=sample.sample_id,
            study_id=sample.study_id,
            well_type="sample",
            repeat_pair=sample.repeat_pair,
            factor_1=sample.factor_1,
            factor_2=sample.factor_2,
            material=sample.material,
            sample_description=sample.sample_description,
            box_id=sample.box_id,
            sample_alias=sample.sample_alias,
        )

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for (r, c), w in self.wells.items():
            rows.append({
                "plate": self.plate_number,
                "well": f"{r}{c}",
                "row": r,
                "col": c,
                "sample_id": w.sample_id or "",
                "study_id": w.study_id or "",
                "well_type": w.well_type,
                "repeat_pair": w.repeat_pair or "",
                "factor_1": w.factor_1 or "",
                "factor_2": w.factor_2 or "",
                "material": w.material or "",
                "sample_description": w.sample_description or "",
                "box_id": w.box_id or "",
                "sample_alias": w.sample_alias or "",
                "label": w.label or "",
            })
        return pd.DataFrame(rows)

    def serialize(self) -> dict:
        wells_dict = {}
        for (r, c), w in self.wells.items():
            wells_dict[f"{r},{c}"] = {
                "row": w.row, "col": w.col,
                "sample_id": w.sample_id,
                "study_id": w.study_id,
                "well_type": w.well_type,
                "repeat_pair": w.repeat_pair,
                "factor_1": w.factor_1,
                "factor_2": w.factor_2,
                "material": w.material,
                "sample_description": w.sample_description,
                "box_id": w.box_id,
                "sample_alias": w.sample_alias,
                "label": w.label,
            }
        return {"plate_number": self.plate_number, "wells": wells_dict}

    @staticmethod
    def deserialize(d: dict) -> "Plate":
        plate = Plate.__new__(Plate)
        plate.plate_number = d["plate_number"]
        plate.wells = {}
        for key, w in d["wells"].items():
            r, c = key.split(",")
            plate.wells[(r, int(c))] = WellAssignment(
                row=r, col=int(c),
                sample_id=w["sample_id"],
                study_id=w["study_id"],
                well_type=w["well_type"],
                repeat_pair=w["repeat_pair"],
                factor_1=w.get("factor_1"),
                factor_2=w.get("factor_2"),
                material=w.get("material"),
                sample_description=w.get("sample_description"),
                box_id=w.get("box_id"),
                sample_alias=w.get("sample_alias"),
                label=w["label"],
            )
        return plate


class PlateOptimizer:
    """
    Assigns samples from one or more studies to Biocrates plates.

    Parameters
    ----------
    plate_capacity : free (non-calibrator) sample well slots per plate. The
                     Biocrates QC1000 layout has 79 genuinely usable sample wells
                     (cols 3-12, plus column 2's two free rows, minus 3 extra
                     reserved QC2 wells) — must be between 1 and MAX_SAMPLE_CAPACITY.
    allow_mixed    : allow samples from different studies on the same plate.
    randomize      : shuffle sample order within each study before assignment.
    balanced       : when a study needs > 1 plate, split evenly (else compact).
    balance_factor : interleave by (factor_1, factor_2) so each plate gets even
                     proportions of each combination (requires randomize=True
                     for within-group shuffling).
    seed           : RNG seed for reproducibility (uses a local RNG instance —
                     does not mutate global random state, so it's safe to use
                     concurrently across requests).
    """

    def __init__(
        self,
        plate_capacity: int = MAX_SAMPLE_CAPACITY,
        allow_mixed: bool = False,
        randomize: bool = True,
        balanced: bool = True,
        balance_factor: bool = True,
        seed: Optional[int] = None,
    ) -> None:
        if not (1 <= plate_capacity <= MAX_SAMPLE_CAPACITY):
            raise ValueError(
                f"Sample well capacity must be between 1 and {MAX_SAMPLE_CAPACITY} "
                f"(got {plate_capacity})."
            )
        self.plate_capacity = plate_capacity
        self.allow_mixed = allow_mixed
        self.randomize = randomize
        self.balanced = balanced
        self.balance_factor = balance_factor
        self._rng = random.Random(seed)

    def _new_plate(self, number: int) -> Plate:
        return Plate(plate_number=number)

    def _make_units(self, samples: List[Sample]) -> List[List[Sample]]:
        """Group samples into atomic units that always land on the same plate, and
        order them for a simple, predictable picking sequence.

        Repeat-pairs are atomic — always placed together (e.g. paired visits,
        technical replicates), which protects the within-pair comparison from
        plate/batch effects. Boxes are NOT atomic: a box is free to span two
        adjacent plates if that's where the fill boundary happens to land. What
        boxes DO get is strict picking order — samples are sorted by box_id
        (natural sort: "Box2" < "Box10", plain integers sort numerically) before
        being grouped, so box1 is fully consumed before box2 starts, etc. A box
        spanning a boundary just means: keep pulling from the same box for the
        next plate too — nothing to track beyond "continue where you left off",
        and it never jumps back to an earlier box or ahead to a later one."""
        sorted_samples = sorted(
            samples, key=lambda s: _natural_sort_key(s.box_id) if s.box_id else []
        )
        units: List[List[Sample]] = []
        pair_unit_index: Dict[str, int] = {}
        for s in sorted_samples:
            if s.repeat_pair:
                if s.repeat_pair in pair_unit_index:
                    units[pair_unit_index[s.repeat_pair]].append(s)
                else:
                    pair_unit_index[s.repeat_pair] = len(units)
                    units.append([s])
            else:
                units.append([s])
        return units

    def _shuffle_within_box_groups(self, units: List[List[Sample]]) -> None:
        """Shuffle `units` in place, but only within each contiguous run that
        shares the same box (units are already grouped that way by _make_units).
        Randomises position within a box's own span for positional-effect
        protection, without disturbing the box-to-box picking sequence."""
        keys = [u[0].box_id if u and u[0].box_id else None for u in units]
        i, n = 0, len(units)
        while i < n:
            j = i
            while j < n and keys[j] == keys[i]:
                j += 1
            segment = units[i:j]
            self._rng.shuffle(segment)
            units[i:j] = segment
            i = j

    @staticmethod
    def _factor_key(unit: List[Sample]) -> Tuple[Optional[str], Optional[str]]:
        """Stratification cell for a unit: the (factor_1, factor_2) combination of its
        first sample (repeat-pair members always share the same factor values — but a
        box unit may be a heterogeneous mix, in which case this is only representative
        of its first sample, since a box moves as one block regardless of factor mix)."""
        if not unit:
            return (None, None)
        return (unit[0].factor_1, unit[0].factor_2)

    @staticmethod
    def _has_any_factor(units: List[List[Sample]]) -> bool:
        return any(f1 or f2 for f1, f2 in (PlateOptimizer._factor_key(u) for u in units))

    def optimize(self, studies_samples: List[List[Sample]]) -> List[Plate]:
        """
        studies_samples : list-of-lists. Each inner list holds all samples for one study.
        Returns         : ordered list of Plate objects.
        """
        if self.allow_mixed:
            # Smart packing: keep whole studies together; only split studies that must be.
            plates = self._assign_mixed(studies_samples)
        else:
            # Strict per-study: every study gets its own dedicated plate(s).
            plates = self._assign_per_study(studies_samples)
        return plates

    # ── Assignment strategies ────────────────────────────────────────────────

    def _assign_per_study(self, studies_samples: List[List[Sample]]) -> List[Plate]:
        all_plates: List[Plate] = []
        counter = [1]

        for study_samples in studies_samples:
            units = self._make_units(list(study_samples))
            total = sum(len(u) for u in units)

            has_factor = self._has_any_factor(units)

            if self.balance_factor and has_factor and total > self.plate_capacity:
                n = int(np.ceil(total / self.plate_capacity))
                study_plates = self._factor_balanced_fill(units, n, counter)
            elif self.balanced and total > self.plate_capacity:
                n = int(np.ceil(total / self.plate_capacity))
                if self.randomize:
                    self._shuffle_within_box_groups(units)
                study_plates = self._balanced_fill(units, n, counter)
            else:
                if self.randomize:
                    self._shuffle_within_box_groups(units)
                study_plates = self._compact_fill(units, counter)

            all_plates.extend(study_plates)

        return all_plates

    def _assign_mixed(self, studies_samples: List[List[Sample]]) -> List[Plate]:
        """
        Smart packing mode — minimises total plate count.

        All studies that physically exceed plate_capacity are packed together into
        a shared pool of plates (rather than each getting isolated plates), minimising
        the total number of plates needed. `balanced` controls how that pool is spread
        across its plates: compact (fill one plate to capacity before starting the
        next) when off, evenly round-robined across all of them when on — same
        semantics as in per-study mode.

        Studies that fit on one plate are always kept whole (never split, regardless
        of `balanced` — there's nothing to spread once a study is confined to one
        plate). They are bin-packed best-fit — placed on whichever existing plate
        (split or fresh) has the least residual space that still fits them — before
        opening a new plate. This already prefers topping off existing plates over
        opening new ones; any leftover gaps are the unavoidable cost of never
        fragmenting a study that fits on one plate.
        """
        counter = [1]

        # Partition: studies that must be split vs. those that can stay whole.
        big   = [ss for ss in studies_samples if len(ss) > self.plate_capacity]
        small = [ss for ss in studies_samples if len(ss) <= self.plate_capacity]

        # ── Step 1: pack ALL big studies together into a shared plate pool ─────────
        # Packing them together (not in isolation) minimises plates: the "tail" of
        # one study fills the space that would otherwise be wasted at the end of
        # another. Studies are concatenated study-by-study (not interleaved), so
        # with compact fill this naturally confines cross-study mixing to at most
        # one boundary plate — no explicit bookkeeping needed, since sequential
        # fill with only small repeat-pairs as atomic units doesn't create the
        # kind of gaps that would otherwise tempt a fancier packer to reach back
        # across studies.
        split_plates: List[Plate] = []

        if big:
            big_units: List[List[Sample]] = []
            for study_samples in sorted(big, key=len, reverse=True):
                samples = list(study_samples)
                units = self._make_units(samples)

                # Pre-interleave this study's own units by (factor_1, factor_2) for
                # a rough per-plate balance as they're laid down sequentially. When
                # spreading evenly (balanced=True) this isn't needed —
                # _factor_balanced_fill below groups and round-robins the whole
                # pool by factor combination directly.
                if self.balance_factor and self._has_any_factor(units) and not self.balanced:
                    factor_groups: Dict[Tuple[Optional[str], Optional[str]], List[List[Sample]]] = {}
                    for u in units:
                        factor_groups.setdefault(self._factor_key(u), []).append(u)
                    queues = list(factor_groups.values())
                    while any(queues):
                        for q in queues:
                            if q:
                                big_units.append(q.pop(0))
                        queues = [q for q in queues if q]
                else:
                    if self.randomize and not (self.balance_factor and self._has_any_factor(units)):
                        self._shuffle_within_box_groups(units)
                    big_units.extend(units)

            has_pool_factor = self.balance_factor and self._has_any_factor(big_units)
            if self.balanced:
                total_big = sum(len(u) for u in big_units)
                n = max(1, int(np.ceil(total_big / self.plate_capacity)))
                if has_pool_factor:
                    split_plates = self._factor_balanced_fill(big_units, n, counter)
                else:
                    split_plates = self._balanced_fill(big_units, n, counter)
            else:
                split_plates = self._compact_fill(big_units, counter)

        # ── Step 2: best-fit bin-pack small studies across split + fresh plates ─────
        packing_plates: List[Plate] = []
        if small:
            prepared = []
            for study_samples in small:
                units = self._make_units(list(study_samples))
                if self.randomize:
                    self._shuffle_within_box_groups(units)
                prepared.append(units)
            prepared.sort(key=lambda us: sum(len(u) for u in us), reverse=True)

            for units in prepared:
                total = sum(len(u) for u in units)
                candidates = [
                    p for p in split_plates + packing_plates
                    if p.capacity_remaining(self.plate_capacity) >= total
                ]
                if candidates:
                    # Best fit: the plate with the least leftover space that still fits,
                    # so larger residuals stay available for later (larger) studies.
                    target = min(candidates, key=lambda p: p.capacity_remaining(self.plate_capacity))
                else:
                    target = self._new_plate(counter[0])
                    counter[0] += 1
                    packing_plates.append(target)

                avail = target.available_positions()
                i = 0
                for unit in units:
                    for s in unit:
                        target.assign_sample(avail[i], s)
                        i += 1

        # ── Step 3: shuffle all plates ───────────────────────────────────────────────
        if self.randomize:
            for p in split_plates + packing_plates:
                self._shuffle_plate_positions(p)

        return split_plates + packing_plates

    def _compact_fill(self, units: List[List[Sample]], counter: List[int]) -> List[Plate]:
        """Sequential fill: accumulate units onto the current plate until the next
        one wouldn't fit, then move on to a new plate — never revisiting an earlier
        one. Since the only atomic (unsplittable) units left are small repeat-pair
        groups, this is at-or-near the mathematically minimal plate count on its
        own (no bin-packing search needed), and it has a useful side effect: it
        naturally confines any cross-study mixing to a single boundary plate
        between two consecutive studies, and keeps box picking order strictly
        sequential — a box that spans a boundary just continues onto the very next
        plate, never jumping back or ahead."""
        plates: List[Plate] = []
        current = self._new_plate(counter[0])
        counter[0] += 1
        n_placed = 0

        for unit in units:
            self._check_unit(unit)
            if n_placed + len(unit) > self.plate_capacity:
                plates.append(current)
                current = self._new_plate(counter[0])
                counter[0] += 1
                n_placed = 0
            avail = current.available_positions()
            for i, s in enumerate(unit):
                current.assign_sample(avail[i], s)
            n_placed += len(unit)

        if any(w.sample_id for w in current.wells.values()):
            plates.append(current)
        return plates

    def _balanced_fill(self, units: List[List[Sample]], n_plates: int, counter: List[int]) -> List[Plate]:
        plates = [self._new_plate(counter[0] + i) for i in range(n_plates)]
        counter[0] += n_plates
        pidx = 0

        for unit in units:
            self._check_unit(unit)
            placed = False
            for _ in range(len(plates)):
                p = plates[pidx % len(plates)]
                if p.capacity_remaining(self.plate_capacity) >= len(unit):
                    avail = p.available_positions()
                    for i, s in enumerate(unit):
                        p.assign_sample(avail[i], s)
                    pidx += 1
                    placed = True
                    break
                pidx += 1

            if not placed:
                extra = self._new_plate(counter[0])
                counter[0] += 1
                avail = extra.available_positions()
                for i, s in enumerate(unit):
                    extra.assign_sample(avail[i], s)
                plates.append(extra)

        return [p for p in plates if any(w.sample_id for w in p.wells.values())]

    def _factor_balanced_fill(
        self, units: List[List[Sample]], n_plates: int, counter: List[int]
    ) -> List[Plate]:
        """
        Distribute units across plates so each (factor_1, factor_2) combination is
        spread proportionally. Strategy: for each combination independently, distribute
        its units across plates via round-robin, then shuffle positions within
        each plate so factor and plate position are not correlated.
        """
        plates = [self._new_plate(counter[0] + i) for i in range(n_plates)]
        counter[0] += n_plates

        # Group units by (factor_1, factor_2) combination
        groups: Dict[Tuple[Optional[str], Optional[str]], List[List[Sample]]] = {}
        for unit in units:
            groups.setdefault(self._factor_key(unit), []).append(unit)

        for factor_units in groups.values():
            if self.randomize:
                self._rng.shuffle(factor_units)
            pidx = 0
            for unit in factor_units:
                self._check_unit(unit)
                placed = False
                for _ in range(len(plates) + 1):
                    p = plates[pidx % len(plates)]
                    if p.capacity_remaining(self.plate_capacity) >= len(unit):
                        avail = p.available_positions()
                        for i, s in enumerate(unit):
                            p.assign_sample(avail[i], s)
                        pidx += 1
                        placed = True
                        break
                    pidx += 1
                if not placed:
                    extra = self._new_plate(counter[0])
                    counter[0] += 1
                    avail = extra.available_positions()
                    for i, s in enumerate(unit):
                        extra.assign_sample(avail[i], s)
                    plates.append(extra)

        # Shuffle within-plate positions so factor level doesn't correlate with well position
        if self.randomize:
            for plate in plates:
                self._shuffle_plate_positions(plate)

        return [p for p in plates if any(w.sample_id for w in p.wells.values())]

    def _shuffle_plate_positions(self, plate: Plate) -> None:
        """Randomly permute sample identities within each study's own block of
        wells. Grouping by study (rather than shuffling the whole plate together)
        preserves whatever spatial separation the fill order already produced —
        when two studies share a plate, each keeps its own contiguous side (e.g.
        left/right) instead of being intermixed well-by-well."""
        occupied = [
            (pos, plate.wells[pos])
            for pos in SAMPLE_POSITIONS
            if plate.wells[pos].well_type == "sample"
        ]
        if len(occupied) <= 1:
            return

        by_study: Dict[Optional[str], List[Tuple[Tuple[str, int], WellAssignment]]] = {}
        for pos, w in occupied:
            by_study.setdefault(w.study_id, []).append((pos, w))

        for group in by_study.values():
            if len(group) <= 1:
                continue
            positions = [pos for pos, _ in group]
            wells = [w for _, w in group]
            self._rng.shuffle(positions)
            for pos, w in zip(positions, wells):
                plate.wells[pos] = WellAssignment(
                    row=pos[0], col=pos[1],
                    sample_id=w.sample_id,
                    study_id=w.study_id,
                    well_type="sample",
                    repeat_pair=w.repeat_pair,
                    factor_1=w.factor_1,
                    factor_2=w.factor_2,
                    material=w.material,
                    sample_description=w.sample_description,
                    box_id=w.box_id,
                    sample_alias=w.sample_alias,
                )

    def _check_unit(self, unit: List[Sample]) -> None:
        if len(unit) > self.plate_capacity:
            pid = unit[0].repeat_pair or unit[0].sample_id
            raise ValueError(
                f"Repeat-pair group '{pid}' has {len(unit)} samples "
                f"but plate capacity is {self.plate_capacity}."
            )
