#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>

int main(void) {
    /* classic exercise: how many processes are created? */
    fork();
    if (fork() == 0) {
        fork();
    }
    for (int i = 0; i < 2; i++) {
        if (fork() && fork())
            break;
    }
    while (wait(NULL) > 0);
    return 0;
}
