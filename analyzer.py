"""
analyzer.py - Analyse the fork() calls made by a C program.

1. The C file is compiled with gcc, force-including a small tracing header
   that replaces every `fork()` call with a wrapper.
2. The wrapper calls the real fork() and, in the parent, appends a line
   "FORK parent_pid child_pid source_line" to a log file.
3. The program is run (with a timeout) and the log is parsed into a
   ForkTrace object.

Because the program is really executed, the result is exact for any code:
loops, conditions, fork() inside && / || expressions, etc.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------
# C tracing header, force-included before the user's code (gcc -include ...)
# ----------------------------------------------------------------------------
TRACER_H = r"""
#ifndef FORK_TREE_TRACER_H
#define FORK_TREE_TRACER_H
#include <sys/types.h>
#include <unistd.h>      /* declare the real fork() BEFORE we define the macro */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void __ft_log(const char *msg) {
    const char *path = getenv("FORK_TREE_LOG");
    if (!path) return;
    int fd = open(path, O_WRONLY | O_APPEND | O_CREAT, 0644);
    if (fd < 0) return;
    write(fd, msg, strlen(msg));   /* O_APPEND + single write => atomic line */
    close(fd);
}

__attribute__((constructor)) static void __ft_root(void) {
    char buf[64];
    snprintf(buf, sizeof buf, "ROOT %d\n", (int)getpid());
    __ft_log(buf);
}

static pid_t __ft_fork(int line) {
    pid_t parent = getpid();
    pid_t r = fork();
    if (r > 0) {
        char buf[96];
        snprintf(buf, sizeof buf, "FORK %d %d %d\n", (int)parent, (int)r, line);
        __ft_log(buf);
    }
    return r;
}

#define fork() __ft_fork(__LINE__)
#endif
"""


@dataclass
class ForkTrace:
    """Result of tracing a program: the root PID and the fork edges."""
    root: int
    edges: list = field(default_factory=list)   # (parent_pid, child_pid, line)
    output: str = ""

    @property
    def children(self):
        kids = defaultdict(list)
        for parent, child, _ in self.edges:      # log order == creation order
            kids[parent].append(child)
        return kids

    @property
    def fork_line(self):
        return {child: line for _, child, line in self.edges}

    @property
    def total(self):
        return len(self.edges) + 1

    def names(self, show_pids=False):
        """Name processes P0, P1, ... in breadth-first order (or by PID)."""
        children, names, queue = self.children, {}, [self.root]
        while queue:
            n = queue.pop(0)
            names[n] = str(n) if show_pids else f"P{len(names)}"
            queue.extend(children.get(n, []))
        return names


def trace_program(c_file, prog_args=(), timeout=10, cflags=()):
    """Compile and run `c_file`, returning a ForkTrace of its fork() calls."""
    if shutil.which("gcc") is None:
        sys.exit("error: gcc not found in PATH")

    work = tempfile.mkdtemp(prefix="fork_tree_")
    try:
        header = os.path.join(work, "fork_tracer.h")
        binary = os.path.join(work, "prog")
        log = os.path.join(work, "fork.log")
        with open(header, "w") as f:
            f.write(TRACER_H)

        cmd = ["gcc", "-w", "-include", header, c_file, "-o", binary, *cflags]
        comp = subprocess.run(cmd, capture_output=True, text=True)
        if comp.returncode != 0:
            sys.exit("compilation failed:\n" + comp.stderr)

        env = dict(os.environ, FORK_TREE_LOG=log)
        # start_new_session so we can kill every descendant on timeout
        proc = subprocess.Popen([binary, *prog_args], env=env,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                start_new_session=True, text=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            out, _ = proc.communicate()
            print(f"warning: program still running after {timeout}s, killed it",
                  file=sys.stderr)

        root, edges = None, []
        if os.path.exists(log):
            with open(log) as f:
                for line in f:
                    parts = line.split()
                    if parts[:1] == ["ROOT"] and root is None:
                        root = int(parts[1])
                    elif parts[:1] == ["FORK"]:
                        edges.append((int(parts[1]), int(parts[2]), int(parts[3])))
        if root is None:
            sys.exit("error: program produced no trace (did it start?)")
        return ForkTrace(root, edges, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
