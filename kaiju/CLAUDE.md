# Kaiju cluster

You are on the login node of Kaiju, a small shared Slurm cluster: this login node plus
compute nodes n1-n8 (52 cores each). Other people work on this node at the same time.

- Model runs, test suites and analysis of large outputs go to the compute nodes through
  `sbatch`. Builds and short container runs (an overlay `pip install`, a quick
  `apptainer exec` check) may run here, using at most 4 cores.
- These commands reach Slurm or Apptainer from here: `squeue`, `sinfo`, `scontrol show`,
  `sbatch`, `scancel`, `srun` and `apptainer`. Run each as a plain single command: no `;`,
  `&&`, `|`, redirects, `$(...)` or `echo $?` on the same line, or it runs inside the
  sandbox and fails. `salloc`, `sacct`, `sstat` and `seff` cannot work from here
  (accounting is not enabled on Kaiju anyway). A finished job's result is in its output
  files; `scontrol show job <id>` works only for a few minutes after it ends.
- `sbatch`, `srun` and `apptainer` run without asking, as the user and outside the
  sandbox, so whatever they execute has the user's full access. Submit only scripts you
  have read, keep submissions few (batch work into job arrays), and don't change files a
  queued job will use. `scancel` asks every time; never cancel jobs you did not submit
  in this session.
- Underworld3 runs from a container. `module load` does not carry over between your
  commands, so name the container in the submission itself. Copy the template into the
  project, then:
  `sbatch --export=ALL,CONTAINER=/opt/cluster/software/containers/underworld3/latest.sif,SCRIPT=/abs/path/model.py kaiju_container_job.sh`
  The template is `/opt/cluster/software/containers/underworld3/kaiju_container_job.sh`;
  use `development.sif` instead of `latest.sif` only when asked for the newest code.
- Compute nodes have no internet access (not even DNS), so a job cannot `pip install`,
  `git clone` or download anything. Fetch what it needs here before submitting.
- Jobs without `--mem` get about 2.6 GB per task and are killed if they exceed it;
  request what the run needs.
- Kaiju has no RDMA. Correctness transfers to other clusters; timings and scaling
  results do not.
- Never use `sudo`, never ask the user for a password, and never suggest loosening the
  sandbox or permission settings. If something is blocked, say so and let the user
  take it to the cluster admin.
- Never print secrets (keys, tokens, anything under `~/.ssh`) into the conversation:
  everything shown here is sent to Anthropic.
