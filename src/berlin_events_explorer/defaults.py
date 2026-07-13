import os
import sys

if getattr(sys, "oxidized", False):
    PACKAGE_MODULE_BASE_FOLDER = "xxx"
    raise NotImplementedError()
elif not hasattr(sys, "_MEIPASS"):
    PACKAGE_MODULE_BASE_FOLDER = os.path.dirname(__file__)
else:
    PACKAGE_MODULE_BASE_FOLDER = os.path.join(sys._MEIPASS, "berlin_events_explorer")

RESOURCES_FOLDER = os.path.join(PACKAGE_MODULE_BASE_FOLDER, "resources")
