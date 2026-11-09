#!/usr/bin/env python3
"""
tree_image.py - Draw the fork() process tree of a C program with Graphviz.

Usage
-----
    uv run tree_image.py program.c                  # -> program_tree.png
    uv run tree_image.py program.c -o tree.svg --show
    uv run tree_image.py program.c --pids           # label nodes with real PIDs
    uv run tree_image.py program.c --args 3 foo     # pass arguments to the program

Requirements: gcc, the Graphviz `dot` binary, and the `graphviz` Python package.
"""

import argparse
import os
import sys

import graphviz

from analyzer import ForkTrace, trace_program

# One colour per generation (depth in the tree), cycling if deeper.
PALETTE = ["#440154", "#3b528b", "#21918c", "#5ec962", "#a5c43a", "#fde725"]


def _depths(trace: ForkTrace):
    children, depth, stack = trace.children, {trace.root: 0}, [trace.root]
    while stack:
        n = stack.pop()
        for k in children.get(n, []):
            depth[k] = depth[n] + 1
            stack.append(k)
    return depth


def build_graph(trace: ForkTrace, title: str, show_pids=False) -> graphviz.Digraph:
    names = trace.names(show_pids)
    depth = _depths(trace)
    fork_line = trace.fork_line

    g = graphviz.Digraph("fork_tree")
    g.attr(rankdir="TB", nodesep="0.35", ranksep="0.6",
           label=f"Process tree of {title}\n"
                 f"{trace.total} processes in total "
                 f"(1 original + {trace.total - 1} created by fork())\n"
                 "edge label = source line of the fork() call",
           labelloc="t", fontsize="14", fontname="Helvetica")
    g.attr("node", shape="circle", style="filled", fontname="Helvetica-Bold",
           fontcolor="white", fixedsize="true",
           width="0.75" if show_pids else "0.55",
           fontsize="10" if show_pids else "12")
    g.attr("edge", color="#888888", arrowsize="0.6",
           fontname="Helvetica", fontsize="9", fontcolor="#c0392b")

    for pid, name in names.items():
        d = depth[pid]
        fill = PALETTE[d % len(PALETTE)]
        g.node(str(pid), name, fillcolor=fill,
               fontcolor="black" if d % len(PALETTE) >= 3 else "white")

    for parent, child, _ in trace.edges:
        g.edge(str(parent), str(child), label=f" L{fork_line[child]}")
    return g


def render(trace: ForkTrace, c_file: str, output: str, show_pids=False, show=False):
    base, ext = os.path.splitext(output)
    fmt = ext.lstrip(".") or "png"
    g = build_graph(trace, os.path.basename(c_file), show_pids)
    g.format = fmt
    path = g.render(filename=base, cleanup=True, view=show)
    print(f"{trace.total} processes ({trace.total - 1} forks). Tree saved to {path}")
    return path


def main():
    ap = argparse.ArgumentParser(description="Draw the fork() process tree of a C program.")
    ap.add_argument("c_file", help="C source file to analyse")
    ap.add_argument("-o", "--output",
                    help="output image; extension picks the format, e.g. .png .svg .pdf "
                         "(default: <file>_tree.png)")
    ap.add_argument("--show", action="store_true", help="open the image after rendering")
    ap.add_argument("--pids", action="store_true", help="label nodes with real PIDs")
    ap.add_argument("--timeout", type=float, default=10, help="seconds before killing the program")
    ap.add_argument("--cflags", default="", help='extra gcc flags, e.g. "-lm"')
    ap.add_argument("--args", nargs=argparse.REMAINDER, default=[],
                    help="arguments passed to the C program (must be last)")
    a = ap.parse_args()

    out = a.output or os.path.splitext(a.c_file)[0] + "_tree.png"
    trace = trace_program(a.c_file, a.args, a.timeout, a.cflags.split())
    if trace.output.strip():
        print("---- program output ----")
        print(trace.output.rstrip())
        print("------------------------")
    try:
        render(trace, a.c_file, out, a.pids, a.show)
    except graphviz.ExecutableNotFound:
        sys.exit("error: Graphviz 'dot' executable not found (install graphviz)")


if __name__ == "__main__":
    main()
