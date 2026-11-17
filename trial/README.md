# Trial run

One small Underworld3 job on Gadi or Setonix, to check that Claude, the `hpc` link and the site's
UW3 container work end to end. Steps: [Quick start, step 7](../README.md#laptop-link-once).

`uw3_trial.py` solves a 2D Stokes flow on a 16 x 16 mesh and writes a parallel checkpoint to
`trial_output/`, in well under a minute on 4 cores. It prints the UW3 version, the MPI library and
the rank count, and as its last line `TRIAL OK`, or `TRIAL FAILED: <reason>` with exit 1. It runs
on any core count and uses only calls in Underworld3 v3.1.0 and v3.2.0.

## For Claude: the job script

Write one job script into `~/hpc/uploads/<site>/trial1/`, next to `uw3_trial.py`. The job starts
in the run folder, so run `uw3_trial.py` there, inside the site's UW3 container. First echo the
resolved image path, so the log records what ran; if `[ -r "$SIF" ]` fails, exit with
`container not readable: $SIF`. Do not use `run` for this trial.

`submit` already passes these on the command line, which overrides `#PBS` and `#SBATCH` lines, so
leave them out of the script:

- Gadi: `-P`, `-N`, `-j oe`, `-m ae`, `-l wd`, `-l walltime=...,ncpus=...,mem=...,storage=...`
- Setonix: `--account`, `--job-name`, `--time`, `--ntasks`, `--nodes`, `--mem`, `--mail-type`

### Gadi (PBS)

| | |
|---|---|
| Directives | `#PBS -q normal` only |
| Modules | `module load singularity` and `module load openmpi/4.1.7` |
| Image | `SIF=$(readlink -f /g/data/m18/software/containers/underworld3/latest.sif)`. The config's `storage` must include `gdata/m18`. |
| Launcher | The block below, which injects the host MPI |
| Log | `trial1.o<job number>` in the run folder |
| MPI line | `Open MPI v4.1.7`, the host's. `v4.1.1`, the container's own, means the injection is missing. |

```bash
HOST_LIBS=/apps/openmpi/4.1.7/lib:/apps/openmpi-mofed5.8-pbs2021.1/4.1.7/lib
HOST_LIBS=$HOST_LIBS:/apps/ucx/1.17.0/lib:/apps/ucc/1.3.0/lib:/apps/hcoll/4.8.3228/lib
HOST_LIBS=$HOST_LIBS:/opt/pbs/default/lib:/half-root/usr/lib64:/half-root/lib64

mpiexec -n "$PBS_NCPUS" singularity exec --bind /half-root --bind /opt/pbs/default/lib "$SIF" \
    bash -c "LD_LIBRARY_PATH=$HOST_LIBS:\$LD_LIBRARY_PATH OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 uw3_trial.py"
```

### Setonix (Slurm)

The member pulls the image once, in a terminal on Setonix:

```bash
module load singularity/4.3.5-mpi
mkdir -p $MYSOFTWARE/containers && cd $MYSOFTWARE/containers
singularity pull underworld3-setonix.sif docker://ghcr.io/underworldcode/underworld3-setonix:latest
```

| | |
|---|---|
| First line | `#!/bin/bash --login`, so `module` works |
| Directives | `#SBATCH --partition=work` and `#SBATCH --cpus-per-task=1` |
| Module | `module load singularity/4.3.5-mpi`. Only `-mpi` binds the host Cray MPICH; add no binds or injection. |
| Image | `SIF=$(readlink -f $MYSOFTWARE/containers/underworld3-setonix.sif)` |
| Threads | `export SINGULARITYENV_OPENBLAS_NUM_THREADS=1 SINGULARITYENV_OMP_NUM_THREADS=1`. Never set `SINGULARITYENV_PYTHONPATH`: it hides petsc4py. |
| Launcher | `srun -N "$SLURM_JOB_NUM_NODES" -n "$SLURM_NTASKS" -c 1 singularity exec "$SIF" python3 uw3_trial.py` |
| Log | `slurm-<job id>.out` in the run folder, unless the script sets `--output` |
| MPI line | `CRAY MPICH`. `MPICH Version: 3.4.3` means the wrong module: ranks talk over TCP. |

## Reading the result

`get` brings the run back to `~/hpc/downloads/<site>/trial1/` (`trial1.2`, ... if taken).

- **Success:** the job log has the line `TRIAL OK` and `trial_output/` holds four
  `checkpoint.mesh.*` files. The script's own lines, and on Gadi the resource-usage summary, may
  follow `TRIAL OK`.
- `.meshes/`, UW3's mesh cache, stays on the cluster: `get` skips hidden folders.
- `TRIAL FAILED: <reason>` names the failed check: the solve, the velocity or the checkpoint.
  `TRIAL FAILED: rank N: ...` is a Python error, with its traceback just above.
- **Gadi: the log stops after `Writing checkpoint`, with `TL_UCP ERROR ... Message truncated` or
  `UCC ERROR` lines, and the job runs out of time:** a hang seen once under host-MPI injection
  ([FINDINGS](https://github.com/underworld-community/uw3-hpc-install-run/blob/main/gadi/container/FINDINGS.md#open-question)).
  Submit once more; if it hangs again, drop the `ucc` and `hcoll` paths from `HOST_LIBS`.
- `container not readable`: on Gadi, `storage` lacks `gdata/m18`; on Setonix, the image is not
  pulled yet.
- Harmless: the `gamg` RuntimeWarning, and on Gadi `openib`, `mlx5_0` and `LOG_CAT_ML` lines.

## If Claude's script fails

Run the tested template the same way. If it passes, Claude's script was at fault; if it fails too,
the site or your setup is. In a terminal on your computer, run the first line and your site's line:

```bash
B=https://raw.githubusercontent.com/underworld-community/uw3-hpc-install-run/main
curl -fsSL $B/gadi/container/gadi_container_job.sh | sed 's/gadi_test_stokes.py/uw3_trial.py/' > ~/hpc/uploads/gadi/trial1/template.sh
curl -fsSL $B/setonix/container/setonix_container_job.slurm | sed 's/setonix_test_stokes.py/uw3_trial.py/' > ~/hpc/uploads/setonix/trial1/template.slurm
```

Then ask Claude to put run `trial1` again and submit `template.sh` (or `template.slurm`) on 4
cores for 10 minutes. The Setonix template logs to `uw3c_<job id>.out`. Templates:
[Gadi](https://github.com/underworld-community/uw3-hpc-install-run/blob/main/gadi/container/gadi_container_job.sh),
[Setonix](https://github.com/underworld-community/uw3-hpc-install-run/blob/main/setonix/container/setonix_container_job.slurm).
