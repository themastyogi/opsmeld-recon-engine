import sys
from pathlib import Path

# Add MCP directory to sys.path for Vercel Serverless Function execution
mcp_dir = Path(__file__).resolve().parent.parent / "MCP"
if str(mcp_dir) not in sys.path:
    sys.path.insert(0, str(mcp_dir))

from web.app import OpsmeldWebHandler

class handler(OpsmeldWebHandler):
    """Vercel Serverless Handler wrapping OpsmeldWebHandler."""
    pass
