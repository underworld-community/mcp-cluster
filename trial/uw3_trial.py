"""Underworld3 trial: a small Stokes solve and a parallel checkpoint, with a verdict.

    mpiexec -n 4 python3 uw3_trial.py        (or srun, inside the site's UW3 container)

Writes ./trial_output/. The last line rank 0 prints is "TRIAL OK", or "TRIAL FAILED: <reason>"
with exit 1. Uses only calls that exist in Underworld3 v3.1.0 and v3.2.0.
"""
import os
import shutil
import sys
import traceback

from mpi4py import MPI

comm = MPI.COMM_WORLD
OUT = "trial_output"
FILES = ["checkpoint.mesh.00000.h5", "checkpoint.mesh.U.00000.h5", "checkpoint.mesh.P.00000.h5",
         "checkpoint.mesh.00000.xdmf"]


def say(*args):
    if comm.rank == 0:
        print(*args, flush=True)


def trial():
    import numpy as np
    import sympy
    from petsc4py import PETSc
    import underworld3 as uw

    t0 = MPI.Wtime()
    say("underworld3:", uw.__version__)
    say("PETSc:", "%d.%d.%d" % PETSc.Sys.getVersion())
    say("MPI ranks:", comm.size)
    say("MPI library:", MPI.Get_library_version().splitlines()[0])
    failures = []

    if comm.rank == 0:
        shutil.rmtree(OUT, ignore_errors=True)  # a rerun must not pass on the last run's files
        os.makedirs(OUT)
    comm.barrier()

    mesh = uw.meshing.UnstructuredSimplexBox(minCoords=(0.0, 0.0), maxCoords=(1.0, 1.0), cellSize=1.0 / 16,
                                             regular=True, qdegree=2)
    v = uw.discretisation.MeshVariable("U", mesh, mesh.dim, degree=2)
    p = uw.discretisation.MeshVariable("P", mesh, 1, degree=1)

    stokes = uw.systems.Stokes(mesh, velocityField=v, pressureField=p)
    stokes.constitutive_model = uw.constitutive_models.ViscousFlowModel
    stokes.constitutive_model.Parameters.viscosity = 1.0
    stokes.bodyforce = sympy.Matrix([0, 0])
    stokes.add_dirichlet_bc([1.0, 0.0], "Top")
    stokes.add_dirichlet_bc([-1.0, 0.0], "Bottom")
    stokes.add_dirichlet_bc([0.0, None], "Left")
    stokes.add_dirichlet_bc([0.0, None], "Right")
    stokes.tolerance = 1.0e-4

    say("Solving ...")
    stokes.solve()
    reason = stokes.snes.getConvergedReason()
    names = {n: k for k, n in vars(PETSc.SNES.ConvergedReason).items() if isinstance(n, int)}
    say("Solve: %s (%d) after %d iterations" % (names.get(reason, "?"), reason, stokes.snes.getIterationNumber()))
    if reason <= 0:
        failures.append("the Stokes solve did not converge (%s)" % names.get(reason, reason))

    data = np.asarray(v.data)
    # MPI's MAX need not propagate NaN, so check it separately.
    finite = comm.allreduce(bool(np.isfinite(data).all()), op=MPI.LAND)
    # The walls fix max |v| at 1 even with no solve; max |v_y|, on the free-slip sides, comes from the solve.
    # It is 0.7704 here and 0.7699 on a 32 x 32 mesh, so 0.01 leaves room for other meshers and solvers.
    vymax = comm.allreduce(float(np.abs(data[:, 1]).max()) if len(data) else 0.0, op=MPI.MAX)
    say("Max |v_y|: %.4f (expected 0.770)" % vymax)
    if not finite or abs(vymax - 0.770) > 0.01:
        failures.append("max |v_y| is %s, expected 0.770" % ("not finite" if not finite else "%.4f" % vymax))

    say("Writing checkpoint to %s/ ..." % OUT)
    mesh.petsc_save_checkpoint(index=0, meshVars=[v, p], outputPath=OUT + "/")
    comm.barrier()
    bad = [f for f in FILES if not (os.path.isfile(os.path.join(OUT, f)) and os.path.getsize(os.path.join(OUT, f)))]
    bad = comm.bcast(bad if comm.rank == 0 else None, root=0)
    say("Checkpoint: %d of %d files written" % (len(FILES) - len(bad), len(FILES)))
    if bad:
        failures.append("checkpoint files missing or empty: " + ", ".join(bad))

    say("Wall time: %.1f s" % (MPI.Wtime() - t0))
    return failures


try:
    failures = trial()
except Exception as e:
    traceback.print_exc()
    sys.stderr.flush()
    print("TRIAL FAILED: rank %d: %s: %s" % (comm.rank, type(e).__name__, e), flush=True)
    # A rank that raised alone would leave the others waiting forever in a collective call.
    if comm.size > 1:
        comm.Abort(1)
    sys.exit(1)

say("TRIAL FAILED: " + "; ".join(failures) if failures else "TRIAL OK")
sys.exit(1 if failures else 0)
