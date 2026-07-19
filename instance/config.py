LANDING_URL = ""
APP_MODE = "DEBUG"
SUBMIT_SECRET = "8y3gCusDsgzYQhKUznLxRDNzNZ1LMZmI"
USER_DATA_FILE = "/home/user/.instanceinfo"
DB_URL = "http://nginx"
TASKFILES_BASE_PATH = "/home/user/tasks/"

# For reading from createdInstances table
DB_CONFIG = {
    "host": "db",
    "dbname": "notebook",
    "user": "read_only_user",
    "password": "%pwUser3%"
}

# For writing to firefox_history table
HISTORY_CONFIG = {
    "host": "db",
    "dbname": "notebook",
    "user": "insert_user",
    "password": "%pwUser2%"
}

# For writing to llm_prompts table
PROMPT_LOG_CONFIG = {
    "host": "db",
    "dbname": "notebook",
    "user": "insert_user",
    "password": "%pwUser2%"
}
