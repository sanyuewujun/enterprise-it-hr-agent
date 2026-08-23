import os
import sys

# 让 pytest 能 import src / scripts 包
sys.path.insert(0, os.path.dirname(__file__))
