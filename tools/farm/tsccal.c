// tsccal [seconds]: print the time-stamp counter's frequency in Hz against CLOCK_MONOTONIC_RAW.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <x86intrin.h>
static void pt(double *t, uint64_t *c) { double best = 1e9; for (int i = 0; i < 400; i++) { struct timespec a, b; clock_gettime(CLOCK_MONOTONIC_RAW, &a); uint64_t x = __rdtsc(); clock_gettime(CLOCK_MONOTONIC_RAW, &b);
    double ta = a.tv_sec + a.tv_nsec * 1e-9, tb = b.tv_sec + b.tv_nsec * 1e-9; if (tb - ta < best) { best = tb - ta; *t = (ta + tb) / 2; *c = x; } } }
int main(int n, char **v) { double t0, t1; uint64_t c0, c1; pt(&t0, &c0); sleep(n > 1 ? atoi(v[1]) : 5); pt(&t1, &c1); printf("%.0f\n", (c1 - c0) / (t1 - t0)); return 0; }
