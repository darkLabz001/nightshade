#!/usr/bin/env python3
import json
import time
import sys

try:
    from wifi_tools import scan_wifi
except Exception as e:
    scan_wifi = None

# simple UI-less radar - just stream? but panel needs to show page
# actually app/ui will call this? maybe we need to make it a long-running script that outputs frames? no
# better: write state and let UI read via app state? maybe not - Nightshade runs scripts and shows output
# easier: make a page in UI that polls scan continuously
pass
