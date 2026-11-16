"""The program frozen into the release build: the g3xn daemon, or with `mcp` the MCP server
that the app's own Claude chat talks to (one program, so the release needs no Python).

    g3xn-daemon.exe [daemon options]      what the Electron window starts
    g3xn-daemon.exe mcp                   the g3xn tools for Claude, over stdio
"""
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        del sys.argv[1]
        from g3xn.mcp_server import main as run
    else:
        from g3xn.daemon import main as run
    run()


if __name__ == "__main__":
    main()
