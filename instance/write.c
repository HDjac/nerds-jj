#include "username.h"

#include <ctype.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/*
 * Processes a user-provided username.
 *
 * Returns:
 *   1 if the username is accepted.
 *   0 if the username is rejected.
 */
int process_username(const char *input, char **username)
{
    /* TODO: Implement the function. */

    /*
     * The function should:
     *  - Accept a username provided by the caller.
     *  - Store the username in the provided buffer.
     *  - Correctly handle arbitrary user input.
     *  - Behave securely for unexpected or invalid input.
     *  - Accept only alphanumeric usernames.
     *  - Reject usernames that are too long for the destination buffer.
     */
}