import subprocess
import os
import sys

LIB_DIR = "libraries"

LOCAL_LIBS = [
    "pyswisseph-2.10.3.2",
    "flatlib-0.2.3",
    "kerykeion-master",
    "VedicAstro-main",
    "sideralib-main",
    "jyotish-master"
]

PYPI_LIBS = [
    "matplotlib",
    "pillow",
    "opencv-python",
    "numpy",
    "pandas",
    "skyfield"
]

def run_cmd(cmd_list):
    try:
        subprocess.run(cmd_list, check=True)
    except subprocess.CalledProcessError:
        print(f"⚠️ Failed to run: {' '.join(cmd_list)}")

def install_local_libs():
    print("\n--- Installing local libraries ---\n")
    for lib in LOCAL_LIBS:
        path = os.path.join(LIB_DIR, lib)
        if os.path.exists(path):
            print(f"Installing {lib} ...")
            run_cmd([sys.executable, "-m", "pip", "install", path])
        else:
            print(f"⚠️ Library not found: {path}")

def install_pypi_libs():
    print("\n--- Installing PyPI libraries ---\n")
    for lib in PYPI_LIBS:
        print(f"Installing {lib} ...")
        run_cmd([sys.executable, "-m", "pip", "install", lib])

def test_installation():
    print("\n--- Testing pyswisseph ---")
    try:
        import swisseph as swe
        print("Swiss Ephemeris version:", swe.version())
    except Exception as e:
        print("pyswisseph test failed:", e)

if __name__ == "__main__":
    install_local_libs()
    install_pypi_libs()
    test_installation()
