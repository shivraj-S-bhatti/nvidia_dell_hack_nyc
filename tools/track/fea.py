"""fea.py -- deterministic 2D linear-elastic FEA on a regular rectangular grid.

Scores topology candidates by compliance (f @ u). This is the evaluator half of a
SIMP topology optimisation; it does not do the optimisation, it only says how stiff
a candidate density field is under one load case.

MODELS
    plane stress, isotropic, linear elastic, small displacement
    bilinear Q4 elements on a uniform grid, 2x2 Gauss quadrature
    SIMP stiffness interpolation  E_e = E * (void_ratio + (1-void_ratio)*rho**penal)

DOES NOT MODEL
    out-of-plane bending or plate/shell behaviour (this is a 2D slice, not a plate)
    contact, friction, or self-intersection of the structure
    geometric or material nonlinearity, plasticity, large rotation
    buckling, fatigue, fracture, or any failure criterion
    dynamics, thermal load, residual stress
A low compliance number here means "stiff in-plane under this one static load", and
nothing else. Do not quote it as a safety margin.

MEASURED ACCURACY (numbers below are from running this file)
    validate_cantilever()  L/H=10 beam, 120x12 elements, tip deflection vs the
                           Timoshenko closed form:      -0.513 % relative error
    validate_symmetry()    mirrored mask + mirrored fixture, compliance:
                                                         3.10e-13 relative difference
    validate_rigid_body()  uniaxial patch test, uniform-strain field:
                                                         8.77e-15 relative error
Q4 elements shear-lock in bending, so the cantilever error is a mesh floor, not
round-off. It converges monotonically from below and is driven by elements through
the depth and by element aspect ratio, measured:

    120x 12 (hx/hy 1.0)  -0.51 %      24x12 (hx/hy 5.0)  -6.67 %
    240x 24 (hx/hy 1.0)  -0.23 %      60x12 (hx/hy 2.0)  -1.34 %
    400x 40 (hx/hy 1.0)  -0.16 %     240x12 (hx/hy 0.5)  -0.30 %

so keep elements near square and put >= 10 of them through a bending depth. The patch
and symmetry results sit at machine precision; those are what pin the assembly, the
constraint reduction and the load consistency.

KNOWN TRAP
    `finite` is exactly what its name says -- np.isfinite over u and compliance. It is
    NOT an "is this fixture sane" flag. An under-constrained fixture that leaves a
    rigid-body mode is only singular in exact arithmetic; SuperLU factors it anyway,
    raises nothing, and returns a finite answer around 1e13 x too large. Callers must
    constrain all three rigid-body modes themselves. A compliance many orders of
    magnitude above the rest of a candidate population is the symptom to watch for.

DETERMINISM
    float64 everywhere, no randomness, fixed COLAMD permutation, SuperLU forced
    (use_umfpack=False). compliance is summed with math.fsum over the loaded DOFs --
    exactly rounded, so it cannot drift with BLAS thread count.
"""
import math
import warnings
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

# 2x2 Gauss-Legendre on [-1,1]^2. Exact for the bilinear Q4; under-integration would
# hourglass and over-integration buys nothing.
_GP = (-1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0))
_GW = 1.0

SOLVER_NAME = "scipy.sparse.linalg.spsolve/SuperLU"


def node_index(ix, iy, nelx):
    """Global node id for grid node (ix, iy). Row-major in y: iy*(nelx+1) + ix."""
    return iy * (nelx + 1) + ix


def _plane_stress_D(E, nu):
    """Plane-stress constitutive matrix, Voigt order (eps_xx, eps_yy, gamma_xy)."""
    return (E / (1.0 - nu * nu)) * np.array(
        [[1.0, nu, 0.0],
         [nu, 1.0, 0.0],
         [0.0, 0.0, 0.5 * (1.0 - nu)]], dtype=np.float64)


def element_stiffness(hx, hy, thickness, E, nu):
    """8x8 Q4 plane-stress stiffness for a rectangle hx wide (x) by hy tall (y).

    Derived by 2x2 Gauss quadrature over the isoparametric bilinear element rather
    than transcribed from a closed form -- the quadrature is checkable term by term
    against a textbook, a pasted 8x8 matrix is not.

    Local node order is counter-clockwise from bottom-left, matching the assembly:
        0=(-1,-1)  1=(+1,-1)  2=(+1,+1)  3=(-1,+1)
    DOF order [u0x,u0y,u1x,u1y,u2x,u2y,u3x,u3y]. Returns (8,8) float64.
    """
    for name, v in (("hx", hx), ("hy", hy), ("thickness", thickness), ("E", E), ("nu", nu)):
        if not np.isfinite(v):
            raise ValueError(f"element_stiffness: {name} must be finite, got {v!r}")
    if hx <= 0 or hy <= 0 or thickness <= 0:
        raise ValueError(f"element_stiffness: hx, hy, thickness must be > 0 "
                         f"(got hx={hx}, hy={hy}, thickness={thickness})")
    if not (-1.0 < nu < 0.5):
        raise ValueError(f"element_stiffness: nu must be in (-1, 0.5), got {nu}")

    D = _plane_stress_D(float(E), float(nu))
    # Rectangle aligned with the axes, so the Jacobian is constant and diagonal.
    det_J = 0.25 * float(hx) * float(hy)
    dxi_dx = 2.0 / float(hx)
    deta_dy = 2.0 / float(hy)

    xi_sign = np.array([-1.0, 1.0, 1.0, -1.0])
    eta_sign = np.array([-1.0, -1.0, 1.0, 1.0])

    k = np.zeros((8, 8), dtype=np.float64)
    for xi in _GP:
        for eta in _GP:
            dN_dxi = 0.25 * xi_sign * (1.0 + eta_sign * eta)
            dN_deta = 0.25 * eta_sign * (1.0 + xi_sign * xi)
            dN_dx = dN_dxi * dxi_dx
            dN_dy = dN_deta * deta_dy

            B = np.zeros((3, 8), dtype=np.float64)
            B[0, 0::2] = dN_dx
            B[1, 1::2] = dN_dy
            B[2, 0::2] = dN_dy
            B[2, 1::2] = dN_dx

            k += (_GW * _GW * det_J * float(thickness)) * (B.T @ D @ B)
    # Kill the asymmetry that floating-point accumulation leaves behind; the operator
    # is symmetric by construction and the factoriser is happier if it is told so.
    return 0.5 * (k + k.T)


@dataclass(eq=False)
class SolveResult:
    """Outcome of one linear solve. See solve() for the exact definitions."""
    u: np.ndarray
    compliance: float
    max_displacement: float
    max_displacement_node: int
    max_displacement_xy: tuple
    element_energy: np.ndarray
    ndof: int
    n_free: int
    n_solid_elements: int
    finite: bool          # np.isfinite(u) and isfinite(compliance) ONLY -- see KNOWN TRAP
    solver: str


def _edof_matrix(nelx, nely):
    """(nel, 8) global DOF ids per element, element e = ey*nelx + ex (mask.ravel() order)."""
    ex, ey = np.meshgrid(np.arange(nelx, dtype=np.int64),
                         np.arange(nely, dtype=np.int64))          # both (nely, nelx)
    n0 = (ey * (nelx + 1) + ex).ravel()
    n1 = n0 + 1
    n2 = n0 + (nelx + 1) + 1
    n3 = n0 + (nelx + 1)
    edof = np.empty((nelx * nely, 8), dtype=np.int64)
    for j, n in enumerate((n0, n1, n2, n3)):
        edof[:, 2 * j] = 2 * n
        edof[:, 2 * j + 1] = 2 * n + 1
    return edof


def _as_dof_array(name, values, ndof, empty_msg):
    """Validated int64 DOF indices. Never truncates: a fractional index is a caller
    bug (usually an off-by-a-half in a node formula) and must not be rounded away."""
    arr = np.asarray(values if isinstance(values, np.ndarray) else list(values))
    if arr.size == 0:
        raise ValueError(f"solve: {name} {empty_msg}")
    if arr.ndim != 1:
        raise ValueError(f"solve: {name} must be a flat sequence of DOF indices, "
                         f"got shape {arr.shape}")
    if not np.issubdtype(arr.dtype, np.integer):
        if not (np.issubdtype(arr.dtype, np.floating) and np.all(np.isfinite(arr))
                and np.all(arr == np.floor(arr))):
            raise ValueError(f"solve: {name} must be integer DOF indices, got dtype "
                             f"{arr.dtype} with non-integral values")
    arr = arr.astype(np.int64)
    bad = arr[(arr < 0) | (arr >= ndof)]
    if bad.size:
        raise ValueError(f"solve: {name} contains out-of-range DOF indices "
                         f"{np.unique(bad)[:8].tolist()}; valid range is [0, {ndof})")
    return arr


def solve(mask, hx, hy, thickness, E, nu, fixed_dofs, loads, penal=3.0, void_ratio=1e-9):
    """Solve K u = f for one density field and return a SolveResult.

    mask       (nely, nelx) float in [0,1]; mask[ey, ex], ey=0 is the y=0 row of
               elements, ex=0 the x=0 column. 1 = solid, 0 = void.
    hx, hy     element width (x) and height (y), model length units (mm).
    thickness  out-of-plane thickness (mm).
    E, nu      Young's modulus (MPa if lengths are mm) and Poisson ratio.
    fixed_dofs iterable of int global DOF indices held at zero. Node n owns DOF
               2*n (x) and 2*n+1 (y).
    loads      iterable of (dof, magnitude) nodal forces (N). Repeats accumulate.
    penal      SIMP penalisation exponent.
    void_ratio stiffness floor, E_e = E*(void_ratio + (1-void_ratio)*rho**penal).
               Must be > 0 or a fully void column of elements leaves the system
               singular and the solve is meaningless rather than merely soft.

    element_energy[ey, ex] is defined exactly as

        E_e * (u_e @ k0 @ u_e)      k0 = element_stiffness(hx, hy, thickness, 1.0, nu)

    i.e. u_e^T k_e u_e with k_e = E_e * k0. That is TWICE the element strain energy,
    chosen so that sum(element_energy) == compliance == f @ u to round-off, which
    makes the per-element field directly usable as the SIMP sensitivity numerator
    and gives a free consistency check on the assembly.
    """
    mask = np.asarray(mask, dtype=np.float64)
    if mask.ndim != 2:
        raise ValueError(f"solve: mask must be 2-D (nely, nelx), got shape {mask.shape}")
    nely, nelx = mask.shape
    if nely == 0 or nelx == 0:
        raise ValueError(f"solve: mask is empty, shape {mask.shape}")
    if not np.all(np.isfinite(mask)):
        raise ValueError("solve: mask contains non-finite values")
    lo, hi = float(mask.min()), float(mask.max())
    if lo < 0.0 or hi > 1.0:
        raise ValueError(f"solve: mask values must lie in [0,1], got [{lo!r}, {hi!r}]")

    for name, v in (("hx", hx), ("hy", hy), ("thickness", thickness), ("E", E),
                    ("nu", nu), ("penal", penal), ("void_ratio", void_ratio)):
        if not np.isfinite(v):
            raise ValueError(f"solve: {name} must be finite, got {v!r}")
    if hx <= 0 or hy <= 0 or thickness <= 0 or E <= 0:
        raise ValueError(f"solve: hx, hy, thickness, E must be > 0 "
                         f"(got hx={hx}, hy={hy}, thickness={thickness}, E={E})")
    if not (-1.0 < nu < 0.5):
        raise ValueError(f"solve: nu must be in (-1, 0.5), got {nu}")
    if penal <= 0:
        raise ValueError(f"solve: penal must be > 0, got {penal}")
    if void_ratio <= 0.0 or void_ratio >= 1.0:
        raise ValueError(f"solve: void_ratio must be in (0,1) -- zero leaves a void "
                         f"region singular -- got {void_ratio}")

    nnode = (nelx + 1) * (nely + 1)
    ndof = 2 * nnode

    fixed = np.unique(_as_dof_array("fixed_dofs", fixed_dofs, ndof,
                                    "is empty; the system would be singular"))

    load_list = list(loads)
    if not load_list:
        raise ValueError("solve: loads is empty; nothing to solve for")
    try:
        load_dofs = _as_dof_array("loads", [d for d, _ in load_list], ndof, "is empty")
        load_mag = np.asarray([m for _, m in load_list], dtype=np.float64)
    except (TypeError, ValueError) as e:
        if "must be" in str(e) or "out-of-range" in str(e) or "is empty" in str(e):
            raise
        raise ValueError(f"solve: loads must be (dof, magnitude) pairs -- {e}") from e
    if not np.all(np.isfinite(load_mag)):
        raise ValueError("solve: loads contains non-finite magnitudes")

    f = np.zeros(ndof, dtype=np.float64)
    np.add.at(f, load_dofs, load_mag)          # accumulate, do not overwrite duplicates

    k0 = element_stiffness(hx, hy, thickness, 1.0, nu)
    rho = mask.ravel()
    simp = float(void_ratio) + (1.0 - float(void_ratio)) * rho ** float(penal)
    E_e = float(E) * simp                                          # (nel,)

    edof = _edof_matrix(nelx, nely)
    # Vectorised triplet assembly: rows repeat the local index a (slow), cols tile the
    # local index b (fast), so the value block must be k0 flattened row-major to match.
    rows = np.repeat(edof, 8, axis=1).ravel()
    cols = np.tile(edof, (1, 8)).ravel()
    vals = (E_e[:, None] * k0.ravel()[None, :]).ravel()
    K = sp.coo_matrix((vals, (rows, cols)), shape=(ndof, ndof)).tocsc()

    free = np.setdiff1d(np.arange(ndof, dtype=np.int64), fixed, assume_unique=False)
    n_free = int(free.size)

    u = np.zeros(ndof, dtype=np.float64)
    finite = True
    if n_free == 0:
        pass                                    # everything constrained: u is exactly zero
    else:
        # Reduce, do not penalise: dropping the constrained rows and columns keeps the
        # condition number honest, where a big diagonal number would hide a bad fixture.
        Kff = K[free, :][:, free]
        ff = f[free]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", spla.MatrixRankWarning)
                uf = spla.spsolve(Kff, ff, permc_spec="COLAMD", use_umfpack=False)
            uf = np.asarray(uf, dtype=np.float64)
            if uf.shape != (n_free,) or not np.all(np.isfinite(uf)):
                finite = False
                uf = np.zeros(n_free, dtype=np.float64)
        except (spla.MatrixRankWarning, RuntimeError, ValueError, MemoryError):
            finite = False
            uf = np.zeros(n_free, dtype=np.float64)
        u[free] = uf

    # f is zero off the loaded DOFs, so this is f @ u exactly. fsum is exactly rounded,
    # so the headline number cannot move with BLAS thread count.
    nz = np.flatnonzero(f)
    compliance = math.fsum((f[nz] * u[nz]).tolist()) if nz.size else 0.0

    disp = np.hypot(u[0::2], u[1::2])
    node = int(np.argmax(disp))                  # argmax takes the first max: deterministic
    max_disp = float(disp[node])
    iy, ix = divmod(node, nelx + 1)

    U = u[edof]                                  # (nel, 8)
    energy = np.einsum("ei,ij,ej->e", U, k0, U, optimize=False) * E_e
    element_energy = energy.reshape(nely, nelx)

    if not (np.all(np.isfinite(u)) and math.isfinite(compliance)):
        finite = False

    return SolveResult(
        u=u,
        compliance=float(compliance),
        max_displacement=max_disp,
        max_displacement_node=node,
        max_displacement_xy=(int(ix), int(iy)),
        element_energy=element_energy,
        ndof=int(ndof),
        n_free=n_free,
        n_solid_elements=int(np.count_nonzero(mask > 0.5)),
        finite=bool(finite),
        solver=SOLVER_NAME,
    )


# ---------------------------------------------------------------------------
# Validators. These are the reason anyone should believe a compliance number out
# of this file. Each one has a closed-form answer, so the error is measurable and
# not a matter of opinion.
# ---------------------------------------------------------------------------

def validate_cantilever(nelx=120, nely=12, verbose=False):
    """Solid cantilever tip deflection vs the Timoshenko closed form.

    L=240 mm, H=24 mm, t=2 mm, E=70000 MPa (aluminium), nu=0.3, P=-100 N.
    Left edge (ix==0) fully clamped, P applied at the mid-height node of ix==nelx.

    The residual error is dominated by Q4 shear locking plus the clamped-edge
    constraint being stiffer than the beam-theory assumption; it falls with nely.
    """
    L, H, t = 240.0, 24.0, 2.0
    E, nu, P = 70000.0, 0.3, -100.0
    if nely % 2:
        raise ValueError(f"validate_cantilever: nely must be even so a mid-height "
                         f"node exists at the tip, got {nely}")
    hx, hy = L / nelx, H / nely

    mask = np.ones((nely, nelx), dtype=np.float64)
    fixed = [d for iy in range(nely + 1)
             for d in (2 * node_index(0, iy, nelx), 2 * node_index(0, iy, nelx) + 1)]
    tip = node_index(nelx, nely // 2, nelx)
    res = solve(mask, hx, hy, t, E, nu, fixed, [(2 * tip + 1, P)])

    fea = float(res.u[2 * tip + 1])
    I = t * H ** 3 / 12.0
    A = t * H
    G = E / (2.0 * (1.0 + nu))
    euler = P * L ** 3 / (3.0 * E * I)
    timo = euler + (6.0 / 5.0) * P * L / (G * A)
    rel = (fea - timo) / timo

    out = {"fea_tip_deflection": fea, "timoshenko_tip_deflection": timo,
           "euler_tip_deflection": euler, "relative_error_vs_timoshenko": rel,
           "L": L, "H": H, "t": t, "E": E, "nu": nu, "P": P,
           "nelx": nelx, "nely": nely}
    if verbose:
        print(f"  cantilever {nelx}x{nely}  fea={fea:.6f} mm  timoshenko={timo:.6f} mm  "
              f"euler={euler:.6f} mm  rel err={rel*100:+.3f} %  ndof={res.ndof}")
    return out


def _mirror_dof(dof, nelx):
    """Map a DOF onto the x-mirrored grid: node (ix,iy) -> (nelx-ix, iy), same component."""
    node, comp = divmod(int(dof), 2)
    iy, ix = divmod(node, nelx + 1)
    return 2 * node_index(nelx - ix, iy, nelx) + comp


def validate_symmetry():
    """Compliance is invariant under mirroring the mask AND the fixture in x.

    The mask is deliberately asymmetric, so this catches an index transposition in the
    assembly (which a symmetric mask would hide) as well as any left/right bias in the
    reduction or the reordering. Returns |cA - cB| / |cA|.
    """
    nelx, nely = 24, 12
    hx = hy = 2.0
    t, E, nu = 3.0, 70000.0, 0.3

    ex, ey = np.meshgrid(np.arange(nelx), np.arange(nely))
    mask = 0.25 + 0.75 * (((ex * 7 + ey * 13) % 5) / 4.0)     # deterministic, asymmetric

    fixed_a = [2 * node_index(0, 0, nelx), 2 * node_index(0, 0, nelx) + 1,
               2 * node_index(nelx, 0, nelx) + 1]
    loads_a = [(2 * node_index(nelx // 2, nely, nelx) + 1, -1000.0),
               (2 * node_index(nelx, nely, nelx), 500.0)]

    # Mirroring an x-force flips its sign; a y-force keeps it.
    fixed_b = [_mirror_dof(d, nelx) for d in fixed_a]
    loads_b = [(_mirror_dof(d, nelx), -m if d % 2 == 0 else m) for d, m in loads_a]

    a = solve(mask, hx, hy, t, E, nu, fixed_a, loads_a)
    b = solve(mask[:, ::-1].copy(), hx, hy, t, E, nu, fixed_b, loads_b)
    return abs(a.compliance - b.compliance) / abs(a.compliance)


def validate_rigid_body():
    """Uniaxial patch test: a uniform-strain field must be reproduced exactly.

    Solid block, left edge held in x, bottom-left corner also held in y (enough to kill
    the three rigid-body modes and nothing more), total force F spread over the right
    edge as consistent Q4 nodal loads -- F/nely on interior nodes, F/(2*nely) on the two
    end nodes. The exact answer is a constant stress F/(H*t):

        ux(x, y) = (F/(A*E)) * x        uy(x, y) = -nu * (F/(A*E)) * y

    which is in the Q4 shape-function space, so any correct implementation hits it to
    machine precision. This is the check that pins load consistency, the constitutive
    matrix and the constraint bookkeeping at once. Returns
    max|u - u_exact| / max|u_exact|.
    """
    nelx, nely = 8, 5                      # odd nely on purpose: no accidental symmetry
    hx, hy = 3.0, 2.0
    t, E, nu = 4.0, 70000.0, 0.3
    F = 1234.5

    W, H = nelx * hx, nely * hy
    A = H * t
    mask = np.ones((nely, nelx), dtype=np.float64)

    fixed = [2 * node_index(0, iy, nelx) for iy in range(nely + 1)]
    fixed.append(2 * node_index(0, 0, nelx) + 1)

    loads = []
    for iy in range(nely + 1):
        share = F / (2.0 * nely) if iy in (0, nely) else F / nely
        loads.append((2 * node_index(nelx, iy, nelx), share))

    res = solve(mask, hx, hy, t, E, nu, fixed, loads)

    eps = F / (A * E)
    ix_g, iy_g = np.meshgrid(np.arange(nelx + 1), np.arange(nely + 1))
    xs = (ix_g * hx).ravel()
    ys = (iy_g * hy).ravel()
    exact = np.empty(res.ndof, dtype=np.float64)
    exact[0::2] = eps * xs
    exact[1::2] = -nu * eps * ys
    return float(np.max(np.abs(res.u - exact)) / np.max(np.abs(exact)))


if __name__ == "__main__":
    import time

    print("fea.py validation")
    print("-" * 58)

    c = validate_cantilever(verbose=True)
    print(f"cantilever  : {c['relative_error_vs_timoshenko']*100:+.4f} %  vs Timoshenko "
          f"({c['nelx']}x{c['nely']} elements)")
    print(f"              fea {c['fea_tip_deflection']:.6f} mm, "
          f"timoshenko {c['timoshenko_tip_deflection']:.6f} mm, "
          f"euler {c['euler_tip_deflection']:.6f} mm")

    s = validate_symmetry()
    print(f"symmetry    : {s:.3e}  relative compliance difference (mirrored fixture)")

    p = validate_rigid_body()
    print(f"patch test  : {p:.3e}  relative error vs the exact uniform-strain field")

    print("-" * 58)
    nelx, nely = 240, 144
    mask = np.ones((nely, nelx), dtype=np.float64)
    fixed = [d for iy in range(nely + 1)
             for d in (2 * node_index(0, iy, nelx), 2 * node_index(0, iy, nelx) + 1)]
    tip = node_index(nelx, nely // 2, nelx)
    t0 = time.perf_counter()
    r = solve(mask, 1.0, 1.0, 2.0, 70000.0, 0.3, fixed, [(2 * tip + 1, -100.0)])
    dt = time.perf_counter() - t0
    print(f"benchmark   : {nelx}x{nely} elements, ndof={r.ndof}, free={r.n_free}, "
          f"{dt:.3f} s, compliance={r.compliance:.6f}")
    print(f"              sum(element_energy)={r.element_energy.sum():.6f} "
          f"(must match compliance), finite={r.finite}")
