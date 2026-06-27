#!/usr/bin/env bash
# Create/refresh the "ibm" conda environment for the helium-VQE Kingston project.
# Usage:
#   bash setup_ibm_env.sh            # create (fails if "ibm" already exists)
#   bash setup_ibm_env.sh --force    # delete existing "ibm" env, recreate
set -euo pipefail

ENV_NAME="ibm"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YML="${HERE}/environment.yml"

# Prefer mamba (much faster) if available, else conda.
if command -v mamba >/dev/null 2>&1; then
  CONDA=mamba
elif command -v conda >/dev/null 2>&1; then
  CONDA=conda
else
  echo "ERROR: neither conda nor mamba found on PATH."
  echo "Install Miniforge first (see SETUP_DELL6.md), then re-run this script."
  exit 1
fi
echo ">> using: $CONDA ($($CONDA --version))"

# Make 'conda activate' work inside a non-interactive script.
CONDA_BASE="$(conda info --base)"
# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  if [[ "${1:-}" == "--force" ]]; then
    echo ">> removing existing env '${ENV_NAME}'"
    conda env remove -n "${ENV_NAME}" -y
  else
    echo "Env '${ENV_NAME}' already exists. Re-run with --force to recreate, or:"
    echo "    conda env update -n ${ENV_NAME} -f ${YML} --prune"
    exit 1
  fi
fi

echo ">> creating env '${ENV_NAME}' from ${YML}"
$CONDA env create -f "${YML}"

echo ">> verifying imports"
conda activate "${ENV_NAME}"
python - <<'PYEOF'
import importlib.metadata as m
pkgs = ["qiskit","qiskit-aer","qiskit-nature","qiskit-ibm-runtime",
        "pyscf","numpy","scipy","matplotlib","sympy"]
print("Python:", __import__("sys").version.split()[0])
ok = True
for p in pkgs:
    try:
        print("  %-20s %s" % (p, m.version(p)))
    except Exception:
        print("  %-20s MISSING" % p); ok = False
# quick functional check: He FCI energy must match exact diag
import importlib.util, os
hh = os.path.join(os.path.dirname(os.path.abspath(".")), "helium_hamiltonian.py")
print("\nFunctional check (He ground state):")
try:
    import helium_hamiltonian as H  # if run from project dir
except Exception:
    H = None
if H:
    b = H.build_helium_hamiltonian()
    d = abs(b.exact_qubit_ground_energy - b.fci_energy)
    print("  exact qubit ground = %.8f Ha; |diff vs FCI| = %.1e" % (b.exact_qubit_ground_energy, d))
    assert d < 1e-6
    print("  OK")
else:
    print("  (run from the project folder to exercise the full check)")
assert ok, "some packages missing"
print("\nEnvironment 'ibm' is ready.")
PYEOF

cat <<'EOM'

Next steps:
  conda activate ibm
  python run_pipeline.py --selftest      # fast logic check
  python run_pipeline.py                 # noiseless / noisy / low-shot demo
  python run_kingston_twin.py            # device-calibrated Kingston twin

To use real IBM Kingston (one-time):
  python -c "from qiskit_ibm_runtime import QiskitRuntimeService; \
QiskitRuntimeService.save_account(token='YOUR_IBM_CLOUD_API_KEY', \
instance='YOUR_CRN', set_as_default=True)"
EOM
