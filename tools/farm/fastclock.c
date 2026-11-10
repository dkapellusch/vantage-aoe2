// fastclock.so: an LD_PRELOAD for the replay farm (see README.md in this folder).
//
// 1. Answers clock_gettime()/gettimeofday() from the CPU's time-stamp counter. On a machine
//    whose kernel clock source is HPET, every clock read is a slow hardware access (about
//    1 us, against 8 ns here), and AoE2 DE under Wine reads the clock so often that it
//    spends half of its main thread there.
// 2. Optionally runs CLOCK_MONOTONIC_RAW faster (FASTCLOCK_RAW_SCALE). That clock is
//    Wine's QueryPerformanceCounter and nothing in the kernel can wait on it, so the game
//    sees time pass faster (lifting its replay speed ceiling) while real waits stay real.
//
// FASTCLOCK_TSC_HZ must hold the counter's frequency (tsccal prints it). Without it, or
// when the CPU's counter is not invariant, every call goes to the kernel as before.
#define _GNU_SOURCE
#include <cpuid.h>
#include <link.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#include <x86intrin.h>

#define NSEC 1000000000LL
static int ready, scaled;
static uint64_t tsc0, mult;           // ns = ticks * mult >> 32
static uint64_t mult_k[8];            // per clock: mult times its speed-up
static int64_t base[8];               // ns of each clock at tsc0
static const unsigned handled = 1u << CLOCK_REALTIME | 1u << CLOCK_MONOTONIC |
                                1u << CLOCK_MONOTONIC_RAW | 1u << CLOCK_BOOTTIME;

// The speed-up applies to every caller except Steam's client library: Wine's ntdll and
// wineserver must agree on the time (waits carry deadlines between them), while Steam's
// own timeouts must not shrink.
static uintptr_t steam_lo, steam_hi;
static int find_steam(struct dl_phdr_info *info, size_t size, void *data) {
    (void)size; (void)data;
    const char *n = info->dlpi_name, *b = n ? strrchr(n, '/') : 0;
    if (!b || strcmp(b + 1, "steamclient.so")) return 0;
    for (int i = 0; i < info->dlpi_phnum; i++) {
        const ElfW(Phdr) *p = &info->dlpi_phdr[i];
        if (p->p_type != PT_LOAD) continue;
        uintptr_t lo = info->dlpi_addr + p->p_vaddr, hi = lo + p->p_memsz;
        if (!steam_lo || lo < steam_lo) steam_lo = lo;
        if (hi > steam_hi) steam_hi = hi;
    }
    return 1;
}

static int real(clockid_t c, struct timespec *ts) { return syscall(SYS_clock_gettime, c, ts); }

__attribute__((constructor)) static void init(void) {
    const char *f = getenv("FASTCLOCK_TSC_HZ");
    double hz = f ? atof(f) : 0;
    unsigned a, b, c, d;
    if (hz < 1e8) return;
    if (!__get_cpuid(0x80000007, &a, &b, &c, &d) || !(d & (1 << 8))) return;  // invariant TSC
    mult = (uint64_t)(1e9 / hz * 4294967296.0);
    tsc0 = __rdtsc();
    // FASTCLOCK_RAW_SCALE: run CLOCK_MONOTONIC_RAW this many times faster. Wine's
    // QueryPerformanceCounter is that clock, and nothing in the kernel can wait on it,
    // so a Windows program sees time pass faster while every real wait stays real.
    const char *sc = getenv("FASTCLOCK_RAW_SCALE");
    double k = sc ? atof(sc) : 1;
    for (int i = 0; i < 8; i++) mult_k[i] = mult;
    if (k > 1 && k <= 1024) {
        mult_k[CLOCK_MONOTONIC_RAW] = (uint64_t)(1e9 / hz * k * 4294967296.0);
        scaled = 1;
    }
    for (int k = 0; k < 8; k++) {
        if (!(handled >> k & 1)) continue;
        uint64_t best = ~0ull;
        for (int i = 0; i < 16; i++) {  // the tightest bracket of counter reads wins
            struct timespec ts;
            uint64_t x = __rdtsc();
            if (real(k, &ts)) return;
            uint64_t y = __rdtsc();
            if (y - x < best) {
                best = y - x;
                uint64_t mid = x + (y - x) / 2 - tsc0;
                base[k] = ts.tv_sec * NSEC + ts.tv_nsec - (int64_t)(((unsigned __int128)mid * mult) >> 32);
            }
        }
    }
    ready = 1;
}

int clock_gettime(clockid_t c, struct timespec *ts) {
    if (ready && (unsigned)c < 8 && (handled >> c & 1)) {
        uint64_t m = mult_k[c];
        if (scaled && c == CLOCK_MONOTONIC_RAW) {
            uintptr_t ra = (uintptr_t)__builtin_return_address(0);
            static unsigned calls;
            // Steam's library is loaded after start-up: look again now and then.
            if (!steam_hi && (++calls & 0xfffff) == 1) dl_iterate_phdr(find_steam, 0);
            if (ra >= steam_lo && ra < steam_hi) m = mult;
        }
        int64_t ns = base[c] + (int64_t)(((unsigned __int128)(__rdtsc() - tsc0) * m) >> 32);
        ts->tv_sec = ns / NSEC;
        ts->tv_nsec = ns % NSEC;
        return 0;
    }
    return real(c, ts);
}

int gettimeofday(struct timeval *restrict tv, void *restrict tz) {
    struct timespec ts;
    (void)tz;
    if (!tv) return 0;
    if (clock_gettime(CLOCK_REALTIME, &ts)) return -1;
    tv->tv_sec = ts.tv_sec;
    tv->tv_usec = ts.tv_nsec / 1000;
    return 0;
}
