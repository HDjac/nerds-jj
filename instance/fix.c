#include "username.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#define USERNAME_SIZE 16

int process_username(const char *input, char **username)
{
    if (input == NULL) {
        return 0;
    }

    for (int i = 0; i < strlen(input); i++) {
        if (!isalnum(input[i])) {
            return 0;
        }
    }

    *username = malloc(USERNAME_SIZE);

    strcpy(*username, input);

    if (strlen(*username) == USERNAME_SIZE - 1) {
        return 0;
    }

    return 1;
}