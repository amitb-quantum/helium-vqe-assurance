# Setting up the `ibm` conda environment on Dell6 (WSL Ubuntu 26.04)

Verified target: WSL2, Ubuntu 26.04, Intel Arc GPU + integrated SoC, 32 GB RAM.
Everything runs on **CPU** — no NVIDIA/CUDA, so we do **not** install
`qiskit-aer-gpu`.

## 0. If you don't have conda yet (Miniforge)

Miniforge gives you `conda` + `mamba` from conda-forge, no license issues:

```bash
cd ~
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash      # so future shells auto-load conda
exec bash            # reload the shell
```

(If `conda` already works, skip this section.)

## 1. Get the project onto Dell6

```bash
cd ~
git clone <your-repo-url> Three-Body     # or: git pull, if already cloned
cd Three-Body/helium-vqe-assurance
```

## 2. Create the environment (one command)

```bash
bash setup_ibm_env.sh
```

This creates an env named **`ibm`** from `environment.yml`, verifies all
imports, and runs a quick helium ground-state check. To rebuild from scratch:

```bash
bash setup_ibm_env.sh --force
```

### Manual equivalent (if you prefer doing it by hand)

```bash
conda env create -f environment.yml
conda activate ibm
python -c "import qiskit, qiskit_aer, qiskit_nature, pyscf; print('ok')"
```

## 3. Run it

```bash
conda activate ibm
python run_pipeline.py --selftest      # fast detector logic check
python run_pipeline.py                 # noiseless / noisy / low-shot demo
python run_kingston_twin.py            # device-calibrated Kingston twin
```

`run_kingston_twin.py` looks for `ibm_kingston_hardware_*.json` in this folder
or its parent; pass `--calib /path/to/file.json` otherwise.

## 4. Connect to real IBM Kingston (when ready)

The legacy `ibm_quantum` channel is retired. Use an **IBM Cloud API key** +
instance CRN (channel defaults to `ibm_quantum_platform`):

```bash
conda activate ibm
python - <<'PY'
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(
    token="YOUR_IBM_CLOUD_API_KEY",
    instance="YOUR_CRN",
    set_as_default=True,
)
print("saved; backends:", [b.name for b in QiskitRuntimeService().backends()][:5])
PY
```

## Pinned versions (what this env installs)

| Package | Version |
|---------|---------|
| python | 3.11 |
| qiskit | 2.4.2 |
| qiskit-aer | 0.17.2 |
| qiskit-nature | 0.8.0 |
| qiskit-ibm-runtime | >=0.40,<0.48 (currently 0.47) |
| pyscf | 2.13.1 |
| numpy / scipy | 2.2.x / 1.15.x |
| matplotlib / sympy | 3.10.x / 1.14.0 |

## Troubleshooting

- **`conda: command not found`** — do Section 0, then `exec bash`.
- **`bash setup_ibm_env.sh` says env exists** — use `--force` to recreate, or
  `conda env update -n ibm -f environment.yml --prune` to update in place.
- **pyscf build/wheel error** — ensure you used the conda Python 3.11 from this
  env (pyscf 2.13.1 ships manylinux wheels for 3.11). `pip cache purge` then
  retry inside the activated env.
- **Anything mentioning CUDA / GPU** — ignore; this project is CPU-only on
  Dell6. Never `pip install qiskit-aer-gpu` here.
- **Slow solve** — the script uses `mamba` automatically if present (Miniforge
  includes it), which is much faster than classic conda.
