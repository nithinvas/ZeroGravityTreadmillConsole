"""Derives each cell's sensitivity from known-weight captures.

The deck is one rigid plate on four cells, so by static equilibrium the four
support reactions always add up to the applied weight, however it is spread.
A capture is therefore an equation, not a single-cell measurement::

    d_TL / c_TL + d_TR / c_TR + d_BR / c_BR + d_BL / c_BL = W

where d is each cell's change from its zero, c its counts per kg, and W the
reference weight. Crediting the whole weight to the one cell it stood over --
the mobile app's original four-corner method -- ignores the load the other three
carried, so those coefficients make the assembled deck read high.

Four captures at spread positions give four equations and so four coefficients.
One capture supports only a single shared coefficient, which is also the fallback
when four positions loaded the cells too similarly to tell them apart.

Ported from the mobile app's `DeckCalibrationSolver`, including its tests. The
maths works in kg per count (k = 1 / c) so the equations are linear.
"""

from __future__ import annotations

from dataclasses import dataclass

CELLS = 4
#: Below this fraction of the system's largest term, a pivot is noise.
SINGULARITY_RATIO = 1e-6
#: Largest believable ratio between the strongest and weakest cell.
MAX_PLAUSIBLE_SPREAD = 5.0
#: A capture whose four cells barely moved carries no information.
MIN_USABLE_COUNTS = 200.0


@dataclass(frozen=True)
class Solution:
    counts_per_kg: tuple[float, float, float, float]
    #: "per_cell" when four independent coefficients were solved, else "shared".
    kind: str


def per_cell_kg_per_count(delta_rows: list[list[float]], known_weight_kg: float) -> list[float] | None:
    """A kg/count per cell from four positions, or None if the captures cannot support it."""
    if known_weight_kg <= 0 or len(delta_rows) != CELLS:
        return None
    if any(len(row) != CELLS for row in delta_rows):
        return None
    solution = _solve([list(map(float, row)) for row in delta_rows], [known_weight_kg] * CELLS)
    if solution is None or any(k == 0.0 for k in solution):
        return None
    # Four identical cells under one deck face the same way: mixed signs, or a
    # large spread, means the solve latched onto noise rather than the cells.
    if any(k > 0 for k in solution) and any(k < 0 for k in solution):
        return None
    magnitudes = [abs(k) for k in solution]
    if max(magnitudes) > min(magnitudes) * MAX_PLAUSIBLE_SPREAD:
        return None
    return solution


def shared_kg_per_count(delta_rows: list[list[float]], known_weight_kg: float) -> float | None:
    """One kg/count for all cells, averaged over every usable capture."""
    if known_weight_kg <= 0:
        return None
    per_row = [known_weight_kg / sum(row) for row in delta_rows if abs(sum(row)) >= MIN_USABLE_COUNTS]
    return sum(per_row) / len(per_row) if per_row else None


def solve(delta_rows: list[list[float]], known_weight_kg: float) -> Solution | None:
    """Per-cell coefficients when four positions allow it, else one shared coefficient."""
    per_cell = per_cell_kg_per_count(delta_rows, known_weight_kg)
    if per_cell is not None:
        c = [1.0 / k for k in per_cell]
        return Solution((c[0], c[1], c[2], c[3]), "per_cell")
    shared = shared_kg_per_count(delta_rows, known_weight_kg)
    if shared is None:
        return None
    return Solution((1.0 / shared,) * 4, "shared")


def _solve(matrix: list[list[float]], constants: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(constants)
    a = [row[:] for row in matrix]
    b = constants[:]
    # Pivots are judged against the largest term: counts run to six figures, so
    # an absolute threshold would accept a system singular in all but arithmetic.
    scale = max(abs(v) for row in a for v in row)
    if scale == 0:
        return None
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < scale * SINGULARITY_RATIO:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        b[col], b[pivot] = b[pivot], b[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            if factor:
                for k in range(col, n):
                    a[row][k] -= factor * a[col][k]
                b[row] -= factor * b[col]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (b[row] - sum(a[row][k] * x[k] for k in range(row + 1, n))) / a[row][row]
    return x
