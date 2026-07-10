"""
Portage Egress Estimator Wrapper
================================
Exposes tools/egress-estimator/egress_estimator.py via the portage package.
"""

import sys
import os

# Locate tools/egress-estimator relative to repo root
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TOOL_DIR = os.path.join(_REPO_ROOT, "tools", "egress-estimator")
if _TOOL_DIR not in sys.path:
    sys.path.insert(0, _TOOL_DIR)

try:
    import egress_estimator as _ee
except ImportError:
    # Fallback if installed via wheel where tools/ might be packaged or adjacent
    _ee = None


def main():
    if _ee is None:
        sys.exit("error: egress_estimator module could not be imported.")
    _ee.main()


if __name__ == "__main__":
    main()
