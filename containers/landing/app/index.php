<?php
//! Copyright (C) 2017 Christian Stransky
//!
//! This software may be modified and distributed under the terms
//! of the MIT license.  See the LICENSE file for details.


define('__DIR__', dirname(__FILE__));
require_once(__DIR__."/../webpageConf/config.php");
require_once('util.php');


// Function to generate participant AI condition.
//
// Even participant ID = AI
// Odd participant ID  = NON_AI
function getAiGroupFromExtRef($ext_ref) {
    $ext_ref = trim((string)$ext_ref);

    if (!preg_match('/^\d+$/', $ext_ref)) {
        return "UNKNOWN";
    }

    $participantId = intval($ext_ref);

    return ($participantId % 2 === 0)
        ? "AI"
        : "NON_AI";
}


if (studyLimitReached()) {
    $webpageMessageHeader = "Study is over";
    $webpageMessage =
        "Thank you for your interest! "
        . "We have already received the maximum number "
        . "of participants for this study.";
    $webpageRedirect = False;

    include(__DIR__."/static/error.php");
    die();
}


$useragent = $_SERVER['HTTP_USER_AGENT'];

if (checkMobile($useragent)) {
    $webpageMessageHeader = "Mobile devices not supported";
    $webpageMessage =
        "Thank you for your interest in our study! "
        . "Sadly this webpage doesn't work with mobile browsers, "
        . "please return with a desktop PC.";
    $webpageRedirect = False;

    include(__DIR__."/static/error.php");
    die();
}


/*
 * Participant ID
 *
 * start.php sends:
 *
 *     ext_ref=<NERDs participant ID>
 *
 * Fall back to pid for compatibility with older NERDs flows.
 */
$rawExtRef =
    $_GET["ext_ref"]
    ?? $_GET["pid"]
    ?? "";

$pid = htmlspecialchars(
    $rawExtRef,
    ENT_QUOTES,
    "UTF-8"
);


/*
 * Recruitment source
 *
 * New Prolific flow sends:
 *
 *     origin=prolific
 *
 * Keep custom1 as a backwards-compatible fallback.
 */
$rawOrigin =
    $_GET["origin"]
    ?? $_GET["custom1"]
    ?? "0";

$originParam = htmlspecialchars(
    trim((string)$rawOrigin),
    ENT_QUOTES,
    "UTF-8"
);


/*
 * Prolific study ID
 *
 * start.php has already validated this value against
 * prolific_main_config.json before forwarding it here.
 *
 * Non-Prolific participants will normally have an empty value.
 */
$rawProlificStudyId =
    $_GET["prolific_study_id"]
    ?? "";

$prolificStudyIdParam = htmlspecialchars(
    trim((string)$rawProlificStudyId),
    ENT_QUOTES,
    "UTF-8"
);


try {
    // Connect to database
    $connect = new PDO(
        "pgsql:host=$dbhost;dbname=$dbname",
        $dbuser,
        $dbpass
    );

    $connect->setAttribute(
        PDO::ATTR_ERRMODE,
        PDO::ERRMODE_EXCEPTION
    );

} catch (PDOException $e) {
    $webpageMessageHeader = "Database error";
    $webpageMessage = $e;
    $webpageRedirect = False;

    include(__DIR__."/static/error.php");
    die();
}


/*
 * If this browser already has an active participant session,
 * resume that participant's existing instance.
 */
if (
    isset($_COOKIE["token"])
    && isset($_COOKIE["userId"])
) {
    $userId = $_COOKIE["userId"];
    $token = $_COOKIE["token"];

    $sth = $connect->prepare(
        'SELECT instanceid AS instanceid
         FROM "createdInstances"
         WHERE userid = :userid
           AND NOT "instanceTerminated"
           AND NOT finished;'
    );

    $sth->bindParam(
        ':userid',
        $userId
    );

    $sth->execute();

    $results = $sth->fetch(
        PDO::FETCH_BOTH
    );

    $instance =
        $results["instanceid"]
        ?? "";

    if (strlen($instance) > 0) {
        header(
            "Location: /proxy/"
            . $instance
            . "/?userId="
            . urlencode($userId)
            . "&token="
            . urlencode($token)
        );

        die();
    }


/*
 * Otherwise, if this participant ID already has an active
 * study instance, resume that instance.
 */
} else if (checkPid($pid)) {

    $sth = $connect->prepare(
        'SELECT instanceid AS instanceid
         FROM "createdInstances"
         WHERE userid = :userid
           AND NOT "instanceTerminated"
           AND NOT finished;'
    );

    $sth->bindParam(
        ':userid',
        $pid
    );

    $sth->execute();

    $results = $sth->fetch(
        PDO::FETCH_BOTH
    );

    $instance =
        $results["instanceid"]
        ?? "";

    if (strlen($instance) > 0) {
        header(
            "Location: /proxy/"
            . $instance
            . "/?userId="
            . urlencode($pid)
            . "&token="
            . urlencode($instance)
        );

        die();
    }
}


/*
 * Default missing origin to legacy value 0.
 */
if ($originParam === "") {
    $originParam = "0";
}


/*
 * Participant ID is required.
 */
if (!checkPid($pid)) {
    $webpageMessageHeader =
        "No participant ID found";

    $webpageMessage =
        "This study must be accessed from the consent survey "
        . "given to you by the study administrators";

    $webpageRedirect = False;

    include(__DIR__."/static/error.php");
    die();
}


/*
 * AI vs NON_AI assignment for display/logging.
 *
 * This is separate from NERDs' internal numeric
 * task-condition system.
 */
$aiGroup =
    getAiGroupFromExtRef(
        $pid
    );


/*
 * Compatibility for pages that still expect $condition.
 */
$condition =
    $aiGroup;


/*
 * static/intro.php will receive:
 *
 * $pid
 * $originParam
 * $prolificStudyIdParam
 * $aiGroup
 * $condition
 */
include("static/intro.php");

?>
