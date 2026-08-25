import os

# display.py sets up a FileHandler pointed at ~/printer_data/logs at import
# time, which is only guaranteed to exist on a real printer install. Create
# it here so tests can import display.py in CI and other dev environments.
os.makedirs(os.path.expanduser("~/printer_data/logs"), exist_ok=True)
