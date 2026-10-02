#!/usr/bin/env bash
# The partition is supplied by submit_gpu_smoke.sh after Atlas configuration
# has been inspected. No partition name is guessed in this file.
#SBATCH --account=disease_ecology
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --time=00:20:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/gconvgru-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/gconvgru-%j.err

set -euo pipefail
source hpc/env_python.sh
python python/gconvgru_smoke.py
