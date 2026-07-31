<?php

define('__DIR__', dirname(__FILE__));
require_once(__DIR__ . "/../webpageConf/config.php");
require_once("util.php");

header("Content-Type: text/plain; charset=utf-8");

$userId = $_POST["userid"] ?? "";
$instanceId = $_POST["instanceid"] ?? "";

if (
    !checkPid($userId) ||
    !preg_match("/^[a-f0-9]{12}$/", $instanceId)
) {
    http_response_code(400);
    echo "error";
    exit;
}

try {
    $connect = new PDO(
        "pgsql:host=$dbhost;dbname=$dbname",
        $dbuser,
        $dbpass
    );

    $connect->setAttribute(
        PDO::ATTR_ERRMODE,
        PDO::ERRMODE_EXCEPTION
    );

    /*
     * Start the clock only once for the participant's current,
     * active study instance.
     */
    $sth = $connect->prepare(
        'UPDATE "createdInstances"
         SET session_start = COALESCE(session_start, NOW())
         WHERE id = (
             SELECT id
             FROM "createdInstances"
             WHERE userid = :userid
               AND instanceid = :instanceid
               AND NOT "instanceTerminated"
               AND NOT finished
               AND instanceid IS NOT NULL
               AND instanceid <> \'error\'
             ORDER BY id DESC
             LIMIT 1
         )
         RETURNING session_start;'
    );

    $sth->bindParam(":userid", $userId);
    $sth->bindParam(":instanceid", $instanceId);
    $sth->execute();

    if ($sth->fetchColumn() === false) {
        http_response_code(409);
        echo "error";
        exit;
    }

    echo "ok";
} catch (PDOException $e) {
    http_response_code(500);
    echo "error";
}
?>
