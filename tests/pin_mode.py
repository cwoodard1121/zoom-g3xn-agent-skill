"""Imported first by every test module: the suite's own tests run in G3Xn mode, whatever
mode this computer's ~/.g3xn/mode.json is in (a G3XN_PEDAL set here reaches subprocesses too)."""
import os

os.environ["G3XN_PEDAL"] = "g3xn"
