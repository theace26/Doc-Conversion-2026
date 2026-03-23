"""
Format handler package — one handler per supported document format.

All handlers extend FormatHandler (formats/base.py) and register themselves
via a class registry so the converter can look up the correct handler by extension.
"""
