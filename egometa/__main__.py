import os

# Silence gRPC info logs (e.g. "Other threads are currently calling into gRPC,
# skipping fork() handlers") emitted by google-generativeai's grpc backend.
# Must be set BEFORE any grpc/genai import.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

import sys
from .cli import main

sys.exit(main())
