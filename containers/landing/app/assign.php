<?php
define('__DIR__', dirname(__FILE__));
require_once(__DIR__."/../webpageConf/config.php");
require_once('util.php');

$csvFile = "/study-data/participant_assignments.csv";

$AI_CONDITION = "AI";
$NON_AI_CONDITION = "NON_AI";
$MIN_ID = 1;
$MAX_ID = 1023;

function normalizeBoolean($value) {
    $value = strtolower(trim((string)$value));
    return in_array($value, ["1", "true", "yes", "y"], true);
}

function readAssignments($csvFile) {
    $rows = [];

    if (!file_exists($csvFile) || filesize($csvFile) === 0) {
        return $rows;
    }

    $file = fopen($csvFile, "r");
    if ($file === false) {
        throw new Exception("Could not open assignment CSV for reading.");
    }

    $header = fgetcsv($file);
    if ($header === false) {
        fclose($file);
        return $rows;
    }

    while (($data = fgetcsv($file)) !== false) {
        $row = [];
        foreach ($header as $index => $field) {
            $row[$field] = $data[$index] ?? "";
        }
        $rows[] = $row;
    }

    fclose($file);
    return $rows;
}

function findExistingAssignment($identifier, $rows) {
    $needle = strtolower(trim($identifier));

    foreach ($rows as $row) {
        if (strtolower(trim($row["identifier"] ?? "")) === $needle) {
            return $row;
        }
    }

    return null;
}

function countDeveloperConditions($rows) {
    $aiCount = 0;
    $nonAiCount = 0;

    foreach ($rows as $row) {
        if (!normalizeBoolean($row["developer"] ?? "")) {
            continue;
        }

        $condition = strtoupper(trim($row["condition"] ?? ""));

        if ($condition === "AI") {
            $aiCount++;
        } elseif ($condition === "NON_AI") {
            $nonAiCount++;
        }
    }

    return [$aiCount, $nonAiCount];
}

function assignCondition($isDeveloper, $rows) {
    global $AI_CONDITION, $NON_AI_CONDITION;

    // Current rule:
    // Developers are balanced across AI/NON_AI.
    // Non-developers are assigned to AI.
    if (!$isDeveloper) {
        return $AI_CONDITION;
    }

    [$aiCount, $nonAiCount] = countDeveloperConditions($rows);

    if ($aiCount < $nonAiCount) {
        return $AI_CONDITION;
    }

    if ($nonAiCount < $aiCount) {
        return $NON_AI_CONDITION;
    }

    return random_int(0, 1) === 0 ? $AI_CONDITION : $NON_AI_CONDITION;
}

function collectExistingIds($rows) {
    $ids = [];

    foreach ($rows as $row) {
        $rawId = trim($row["participant_id"] ?? "");

        if (ctype_digit($rawId)) {
            $ids[(int)$rawId] = true;
        }
    }

    return $ids;
}

function generateParticipantId($condition, $existingIds) {
    global $AI_CONDITION, $MIN_ID, $MAX_ID;

    // AI = even PID, NON_AI = odd PID
    $requiredParity = ($condition === $AI_CONDITION) ? 0 : 1;

    $available = [];

    for ($id = $MIN_ID; $id <= $MAX_ID; $id++) {
        if ($id % 2 === $requiredParity && !isset($existingIds[$id])) {
            $available[] = $id;
        }
    }

    if (count($available) === 0) {
        throw new Exception("No unused participant IDs remain for condition: " . $condition);
    }

    return $available[random_int(0, count($available) - 1)];
}

function appendAssignment($csvFile, $assignment) {
    $fileExists = file_exists($csvFile);
    $fileEmpty = !$fileExists || filesize($csvFile) === 0;

    $file = fopen($csvFile, "a");
    if ($file === false) {
        throw new Exception("Could not open assignment CSV for writing.");
    }

    if (!flock($file, LOCK_EX)) {
        fclose($file);
        throw new Exception("Could not lock assignment CSV.");
    }

    if ($fileEmpty) {
        fputcsv($file, [
            "identifier",
            "participant_id",
            "developer",
            "condition",
            "assigned_at"
        ]);
    }

    fputcsv($file, [
        $assignment["identifier"],
        $assignment["participant_id"],
        $assignment["developer"],
        $assignment["condition"],
        $assignment["assigned_at"]
    ]);

    fflush($file);
    flock($file, LOCK_UN);
    fclose($file);
}

try {
    $identifier = trim($_GET["identifier"] ?? "");
    $developerRaw = $_GET["developer"] ?? "";

    if ($identifier === "") {
        throw new Exception("Missing identifier.");
    }

    if (!preg_match('/^[A-Za-z0-9._@-]+$/', $identifier)) {
        throw new Exception("Invalid identifier format.");
    }

    if ($developerRaw === "") {
        throw new Exception("Missing developer value.");
    }

    $isDeveloper = normalizeBoolean($developerRaw);

    $rows = readAssignments($csvFile);

    $existing = findExistingAssignment($identifier, $rows);

    if ($existing !== null) {
        $participantId = $existing["participant_id"];
    } else {
        $condition = assignCondition($isDeveloper, $rows);
        $existingIds = collectExistingIds($rows);
        $participantId = generateParticipantId($condition, $existingIds);

        appendAssignment($csvFile, [
            "identifier" => $identifier,
            "participant_id" => (string)$participantId,
            "developer" => $isDeveloper ? "1" : "0",
            "condition" => $condition,
            "assigned_at" => gmdate("c")
        ]);
    }

    header("Location: /index.php?ext_ref=" . urlencode($participantId));
    exit();

} catch (Exception $e) {
    $webpageMessageHeader = "Assignment error";
    $webpageMessage = htmlspecialchars($e->getMessage(), ENT_QUOTES, "UTF-8");
    $webpageRedirect = False;
    include(__DIR__."/static/error.php");
    die();
}
?>