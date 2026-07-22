<?php
define('__DIR__', dirname(__FILE__));
require_once(__DIR__."/../webpageConf/config.php");
require_once('util.php');

$csvFile = "/study-data/participant_assignments.csv";

function participantExists($csvFile, $participantId) {
    if (!file_exists($csvFile) || filesize($csvFile) === 0) {
        return false;
    }

    $file = fopen($csvFile, "r");
    if ($file === false) {
        return false;
    }

    $header = fgetcsv($file);
    if ($header === false) {
        fclose($file);
        return false;
    }

    $pidIndex = array_search("participant_id", $header);

    if ($pidIndex === false) {
        fclose($file);
        return false;
    }

    while (($data = fgetcsv($file)) !== false) {
        $rowPid = trim($data[$pidIndex] ?? "");

        if ($rowPid === $participantId) {
            fclose($file);
            return true;
        }
    }

    fclose($file);
    return false;
}

try {
    $participantId = trim($_GET["participant_id"] ?? $_GET["ext_ref"] ?? "");

    if ($participantId === "") {
        throw new Exception("Missing participant ID.");
    }

    if (!preg_match('/^\d+$/', $participantId)) {
        throw new Exception("Invalid participant ID.");
    }

    if (!participantExists($csvFile, $participantId)) {
        throw new Exception("Participant ID was not found in the assignment file.");
    }

    header("Location: /index.php?ext_ref=" . urlencode($participantId));
    exit();

} catch (Exception $e) {
    $webpageMessageHeader = "Study start error";
    $webpageMessage = htmlspecialchars($e->getMessage(), ENT_QUOTES, "UTF-8");
    $webpageRedirect = False;
    include(__DIR__."/static/error.php");
    die();
}
?>