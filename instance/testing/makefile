CC = gcc

CFLAGS = -Wall -Wextra -Wpedantic -std=c11 -g

TARGET = test_username

SRCS = username.c test_username.c

OBJS = $(SRCS:.c=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $(TARGET) $(OBJS)

username.o: username.c username.h
	$(CC) $(CFLAGS) -c username.c

test_username.o: test_username.c username.h
	$(CC) $(CFLAGS) -c test_username.c

run: $(TARGET)
	./$(TARGET)

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all run clean
