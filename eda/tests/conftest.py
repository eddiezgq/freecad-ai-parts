import os
import sys

EDA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(EDA)
sys.path.insert(0, EDA)
DESIGNS = os.path.join(REPO, "factory", "designs")
EXAMPLE_CAP = os.path.join(EDA, "examples", "factories", "example-smt.yaml")
