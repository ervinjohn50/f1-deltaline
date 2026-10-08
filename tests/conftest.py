import os

# Run Qt without a screen, so the app tests also work on GitHub's test machines.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
