#define _POSIX_C_SOURCE 200809L

#include <locale.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "username.h"

/*
 * Post-study grading harness for process_username().
 *
 * IMPORTANT:
 * This file is separate from the participant-facing NERDS test harness.
 * Do not replace or modify test_username.c.
 *
 * Each test runs in a separate child process so that a crash,
 * sanitizer failure, or timeout does not stop the rest of grading.
 */

#define TEST_TIMEOUT_SECONDS 3

/*
 * Allocation wrappers let the grading build:
 *
 *   1. force allocation failure;
 *   2. detect allocations left live after process_username returns.
 *
 * The executable must be linked with:
 *
 *   -Wl,--wrap=malloc
 *   -Wl,--wrap=calloc
 *   -Wl,--wrap=realloc
 *   -Wl,--wrap=strdup
 *   -Wl,--wrap=free
 */

static volatile sig_atomic_t g_fail_allocations = 0;
static long g_live_allocations = 0;

void *__real_malloc(size_t size);
void *__real_calloc(size_t nmemb, size_t size);
void *__real_realloc(void *ptr, size_t size);
char *__real_strdup(const char *s);
void __real_free(void *ptr);


void *__wrap_malloc(size_t size)
{
    void *p;

    if (g_fail_allocations) {
        return NULL;
    }

    p = __real_malloc(size);

    if (p != NULL) {
        g_live_allocations++;
    }

    return p;
}


void *__wrap_calloc(size_t nmemb, size_t size)
{
    void *p;

    if (g_fail_allocations) {
        return NULL;
    }

    p = __real_calloc(nmemb, size);

    if (p != NULL) {
        g_live_allocations++;
    }

    return p;
}


void *__wrap_realloc(void *ptr, size_t size)
{
    void *p;

    if (g_fail_allocations) {
        return NULL;
    }

    p = __real_realloc(ptr, size);

    if (ptr == NULL && p != NULL) {
        g_live_allocations++;
    } else if (ptr != NULL && size == 0 && p == NULL) {
        g_live_allocations--;
    }

    return p;
}


char *__wrap_strdup(const char *s)
{
    char *p;

    if (g_fail_allocations) {
        return NULL;
    }

    p = __real_strdup(s);

    if (p != NULL) {
        g_live_allocations++;
    }

    return p;
}


void __wrap_free(void *ptr)
{
    if (ptr != NULL) {
        g_live_allocations--;
    }

    __real_free(ptr);
}


typedef enum {
    NORMAL_CALL,
    NULL_OUTPUT_POINTER,
    FORCE_ALLOCATION_FAILURE
} TestMode;


typedef struct {
    const char *name;
    const char *input;
    int expected_return;
    const char *expected_username;
    TestMode mode;
} TestCase;


/*
 * With -fsigned-char, 0xff becomes a negative plain-char value.
 *
 * A correct isalnum() implementation should cast to unsigned char
 * before calling ctype functions.
 *
 * Passing this test does NOT by itself prove correct ctype usage;
 * source inspection is still required for that rubric item.
 */
static const char high_bit_input[] = {
    'a',
    (char)0xff,
    'b',
    '\0'
};


static const TestCase tests[] = {

    /* ---------- Valid input ---------- */

    {
        "valid short username",
        "alice",
        1,
        "alice",
        NORMAL_CALL
    },

    {
        "valid alphanumeric username",
        "Alice123",
        1,
        "Alice123",
        NORMAL_CALL
    },

    {
        "valid one-character username",
        "a",
        1,
        "a",
        NORMAL_CALL
    },

    /*
     * USERNAME_SIZE is 16.
     *
     * 15 username characters + terminating NUL = 16 bytes.
     * This is therefore the maximum valid username.
     */
    {
        "valid maximum-length username (15 chars)",
        "Abcdefghijk1234",
        1,
        "Abcdefghijk1234",
        NORMAL_CALL
    },


    /* ---------- Invalid parameters ---------- */

    {
        "NULL input",
        NULL,
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "NULL username out-parameter",
        "alice",
        0,
        NULL,
        NULL_OUTPUT_POINTER
    },


    /* ---------- Invalid characters ---------- */

    {
        "contains underscore",
        "alice_123",
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "contains hyphen",
        "alice-123",
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "contains space",
        "alice bob",
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "contains punctuation",
        "alice!",
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "contains newline",
        "alice\n",
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "contains tab",
        "alice\tbob",
        0,
        NULL,
        NORMAL_CALL
    },

    {
        "contains high-bit non-ASCII byte",
        high_bit_input,
        0,
        NULL,
        NORMAL_CALL
    },


    /* ---------- Length / overflow boundaries ---------- */

    /*
     * 16 characters require 17 bytes including NUL and therefore
     * cannot fit in a USERNAME_SIZE == 16 destination.
     */
    {
        "too long by one byte (16 chars)",
        "Abcdefghijk12345",
        0,
        NULL,
        NORMAL_CALL
    },

    /*
     * Intended to expose solutions that copy before checking length.
     * AddressSanitizer should catch an overflow if one occurs.
     */
    {
        "substantially oversized username",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789ABCDEFGH",
        0,
        NULL,
        NORMAL_CALL
    },


    /* ---------- Allocation handling ---------- */

    {
        "allocation failure",
        "alice",
        0,
        NULL,
        FORCE_ALLOCATION_FAILURE
    }
};


static int run_test_body(const TestCase *test)
{
    int actual;
    char *username = NULL;
    long live_after_call;

    g_live_allocations = 0;
    g_fail_allocations = 0;


    /*
     * Test output-parameter validation separately because passing
     * NULL to an unsafe implementation may crash.
     */
    if (test->mode == NULL_OUTPUT_POINTER) {

        actual = process_username(test->input, NULL);

        live_after_call = g_live_allocations;

        if (actual != test->expected_return) {
            return 1;
        }

        if (live_after_call != 0) {
            return 1;
        }

        return 0;
    }


    /*
     * Make malloc/calloc/realloc/strdup return NULL during the
     * participant function.
     */
    if (test->mode == FORCE_ALLOCATION_FAILURE) {
        g_fail_allocations = 1;
    }


    actual = process_username(test->input, &username);


    /*
     * Do not allow the grading framework itself to inherit the
     * forced-allocation-failure state.
     */
    g_fail_allocations = 0;

    live_after_call = g_live_allocations;


    if (actual != test->expected_return) {
        return 1;
    }


    if (test->expected_return == 1) {

        if (username == NULL) {
            return 1;
        }

        /*
         * strcmp() is intentionally executed while sanitizers are
         * enabled. A missing NUL terminator may therefore be detected.
         */
        if (strcmp(username, test->expected_username) != 0) {
            __wrap_free(username);
            return 1;
        }

        /*
         * At successful return, exactly the returned username
         * allocation should remain live.
         */
        if (live_after_call != 1) {
            __wrap_free(username);
            return 1;
        }

        __wrap_free(username);

        if (g_live_allocations != 0) {
            return 1;
        }

    } else {

        /*
         * This matches the participant-facing harness:
         * rejected input must leave username == NULL.
         */
        if (username != NULL) {
            return 1;
        }

        /*
         * Rejection must not leave allocated memory behind.
         */
        if (live_after_call != 0) {
            return 1;
        }
    }


    return 0;
}


static int run_isolated_test(const TestCase *test)
{
    pid_t pid;
    int status;

    /*
     * Prevent buffered parent output from being printed twice
     * after fork().
     */
    fflush(NULL);

    pid = fork();

    if (pid < 0) {
        printf("[ERROR] %s (fork failed)\n", test->name);
        return 0;
    }


    if (pid == 0) {

        int failed;

        alarm(TEST_TIMEOUT_SECONDS);

        failed = run_test_body(test);

        exit(failed ? 1 : 0);
    }


    if (waitpid(pid, &status, 0) < 0) {
        printf("[ERROR] %s (waitpid failed)\n", test->name);
        return 0;
    }


    if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        printf("[PASS] %s\n", test->name);
        return 1;
    }


    if (WIFSIGNALED(status)) {

        int sig = WTERMSIG(status);

        if (sig == SIGALRM) {
            printf("[TIMEOUT] %s\n", test->name);
        } else {
            printf(
                "[CRASH] %s (signal %d)\n",
                test->name,
                sig
            );
        }

        return 0;
    }


    printf("[FAIL] %s\n", test->name);

    return 0;
}


int main(void)
{
    size_t i;
    int passed = 0;

    const int total =
        (int)(sizeof(tests) / sizeof(tests[0]));


    /*
     * Make character classification deterministic during grading.
     */
    if (setlocale(LC_CTYPE, "C") == NULL) {
        fprintf(stderr, "Unable to set C locale.\n");
        return 2;
    }


    printf(
        "Enhanced process_username grading tests\n"
    );

    printf(
        "=======================================\n"
    );


    for (
        i = 0;
        i < sizeof(tests) / sizeof(tests[0]);
        i++
    ) {
        passed += run_isolated_test(&tests[i]);
    }


    printf(
        "\nMandatory tests passed %d/%d.\n",
        passed,
        total
    );


    if (passed != total) {

        printf("GRADING_RESULT=FAIL\n");

        return 1;
    }


    printf("GRADING_RESULT=PASS\n");

    return 0;
}
