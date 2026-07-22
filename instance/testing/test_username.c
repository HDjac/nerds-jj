#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "username.h"

typedef struct {
    const char *name;
    const char *input;
    int expected;
    const char *expected_username;
} TestCase;

int main(void)
{
    TestCase tests[] = {
        {"valid short username", "alice", 1, "alice"},
        {"valid alphanumeric username", "alice123", 1, "alice123"},
        {"valid one-character username", "a", 1, "a"},
        {"empty username", NULL, 0, NULL},
        {"contains underscore", "alice_123", 0, NULL},
        {"contains hyphen", "alice-123", 0, NULL},
        {"contains space", "alice bob", 0, NULL},
        {"contains punctuation", "alice!", 0, NULL},
        {"contains symbol", "admin@root", 0, NULL},
        {"contains newline", "alice\n", 0, NULL},
        {"contains tab", "alice\tbob", 0, NULL}
    };

    int passed = 0;
    int total = sizeof(tests) / sizeof(tests[0]);

    for (int i = 0; i < total; i++) {
        char *username = NULL;

        int actual = process_username(tests[i].input, &username);

        int result_ok = (actual == tests[i].expected);
        int output_ok = 1;

        if (tests[i].expected == 1) {
            output_ok = (username != NULL &&
                         strcmp(username, tests[i].expected_username) == 0);
        } else {
            output_ok = (username == NULL);
        }

        if (result_ok && output_ok) {
            printf("[PASS] %s\n", tests[i].name);
            passed++;
        } else {
            printf("[FAIL] %s\n", tests[i].name);
            printf("       Input:    \"%s\"\n", tests[i].input);
            printf("       Expected return: %d\n", tests[i].expected);
            printf("       Actual return:   %d\n", actual);

            if (tests[i].expected_username != NULL) {
                printf("       Expected username: \"%s\"\n",
                       tests[i].expected_username);
            } else {
                printf("       Expected username: NULL\n");
            }

            if (username != NULL) {
                printf("       Actual username:   \"%s\"\n", username);
            } else {
                printf("       Actual username:   NULL\n");
            }
        }

        free(username);
    }

    printf("\nPassed %d/%d tests.\n", passed, total);

    return 0;
}