<?php

define('__DIR__', dirname(__FILE__));
require_once(__DIR__ . "/../webpageConf/config.php");
require_once("util.php");

header("Content-Type: application/json; charset=utf-8");
header("Cache-Control: no-store");

$instanceId = $_GET["instanceId"] ?? "";

if (!preg_match("/^[a-f0-9]{12}$/", $instanceId)) {
    http_response_code(400);
    echo json_encode([
        "ok" => false,
        "error" => "invalid_parameters"
    ]);
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

    $sth = $connect->prepare(
        'SELECT
            session_start,
            finished,
            "instanceTerminated",
            CASE
                WHEN session_start IS NULL THEN NULL
                ELSE GREATEST(
                    0,
                    FLOOR(
                        EXTRACT(
                            EPOCH FROM (
                                session_start
                                + INTERVAL \'1 hour\'
                                - NOW()
                            )
                        )
                    )
                )::integer
            END AS remaining_seconds
         FROM "createdInstances"
         WHERE instanceid = :instanceid
         ORDER BY id DESC
         LIMIT 1;'
    );

    $sth->bindParam(":instanceid", $instanceId);
    $sth->execute();

    $row = $sth->fetch(PDO::FETCH_ASSOC);

    if (!$row) {
        http_response_code(404);
        echo json_encode([
            "ok" => false,
            "error" => "session_not_found"
        ]);
        exit;
    }

    $started = $row["session_start"] !== null;
    $remaining = $row["remaining_seconds"];

    echo json_encode([
        "ok" => true,
        "started" => $started,
        "remaining_seconds" => (
            $remaining === null ? null : (int)$remaining
        ),
        "expired" => (
            $started &&
            $remaining !== null &&
            (int)$remaining <= 0
        ),
        "finished" => filter_var(
            $row["finished"],
            FILTER_VALIDATE_BOOLEAN
        ),
        "terminated" => filter_var(
            $row["instanceTerminated"],
            FILTER_VALIDATE_BOOLEAN
        )
    ]);
} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode([
        "ok" => false,
        "error" => "database_error"
    ]);
}
?>
