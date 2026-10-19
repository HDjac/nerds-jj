<?php
//! Copyright (C) 2017 Christian Stransky
//!
//! This software may be modified and distributed under the terms
//! of the MIT license.  See the LICENSE file for details.


define('__DIR__', dirname(__FILE__));

require_once(
    __DIR__ . "/../webpageConf/config.php"
);

require_once(
    __DIR__ . '/../vendor/autoload.php'
);

require_once(
    'util.php'
);


/*
 * Participant ID
 */
$token = trim(
    (string)(
        $_POST['pid']
        ?? ""
    )
);

$token2 = generateAlphanumeric(12);


/*
 * Recruitment source
 *
 * Expected Prolific value:
 *
 *     prolific
 *
 * Older/non-Prolific flows may send 0 or nothing.
 */
$recruitmentSource = trim(
    (string)(
        $_POST["origin"]
        ?? "0"
    )
);


/*
 * Prolific study ID
 *
 * This should only contain a value for Prolific
 * participants.
 */
$prolificStudyId = trim(
    (string)(
        $_POST["prolific_study_id"]
        ?? ""
    )
);


$remoteIp = get_ip();


/*
 * Validate participant ID.
 */
if (
    $token === ""
    || !preg_match(
        '/^\d+$/',
        $token
    )
) {
    $webpageMessageHeader =
        "No participant ID found";

    $webpageMessage =
        "You must access this site with a valid participant ID.";

    $webpageRedirect = False;

    include(
        __DIR__ . "/static/error.php"
    );

    die();
}


/*
 * Normalize recruitment source.
 */
if ($recruitmentSource === "") {
    $recruitmentSource = "0";
}


/*
 * Only allow simple recruitment-source values.
 */
if (
    !preg_match(
        '/^[A-Za-z0-9_-]{1,32}$/',
        $recruitmentSource
    )
) {
    $webpageMessageHeader =
        "Invalid Parameters";

    $webpageMessage =
        "Your recruitment source was invalid.";

    $webpageRedirect = False;

    include(
        __DIR__ . "/static/error.php"
    );

    die();
}


/*
 * Normalize Prolific metadata.
 *
 * The old integer origin column is retained for
 * backwards compatibility:
 *
 *     1 = Prolific
 *     0 = non-Prolific / legacy
 */
$isProlific =
    strtolower($recruitmentSource)
    === "prolific";

$originCode =
    $isProlific
    ? 1
    : 0;


/*
 * A Prolific participant must have a study ID.
 */
if ($isProlific) {

    if ($prolificStudyId === "") {

        $webpageMessageHeader =
            "Invalid Parameters";

        $webpageMessage =
            "The Prolific study ID was missing.";

        $webpageRedirect = False;

        include(
            __DIR__ . "/static/error.php"
        );

        die();
    }

    if (
        !preg_match(
            '/^[A-Za-z0-9_-]{6,128}$/',
            $prolificStudyId
        )
    ) {

        $webpageMessageHeader =
            "Invalid Parameters";

        $webpageMessage =
            "The Prolific study ID was invalid.";

        $webpageRedirect = False;

        include(
            __DIR__ . "/static/error.php"
        );

        die();
    }

} else {

    /*
     * Do not preserve a stray Prolific study ID
     * for a non-Prolific participant.
     */
    $prolificStudyId = "";
}


/*
 * Variables retained for compatibility with
 * the existing static pages.
 */
$originParam = htmlspecialchars(
    $recruitmentSource,
    ENT_QUOTES,
    "UTF-8"
);

$prolificStudyIdParam = htmlspecialchars(
    $prolificStudyId,
    ENT_QUOTES,
    "UTF-8"
);


/*
 * Generate participant AI condition.
 *
 * Even participant ID = AI
 * Odd participant ID  = NON_AI
 */
function getAiGroupFromExtRef(
    $ext_ref
) {

    $ext_ref = trim(
        (string)$ext_ref
    );

    if (
        !preg_match(
            '/^\d+$/',
            $ext_ref
        )
    ) {

        return "UNKNOWN";
    }

    $participantId =
        intval($ext_ref);

    return (
        $participantId % 2 === 0
    )
        ? "AI"
        : "NON_AI";
}


$aiGroup =
    getAiGroupFromExtRef(
        $token
    );


/*
 * Compatibility for static/howTo.php.
 */
$condition =
    $aiGroup;


/*
 * Validate captcha.
 */
function validateCaptcha() {

    global
        $reCaptchaSecret,
        $remoteIp;

    if (
        isset(
            $_POST[
                "g-recaptcha-response"
            ]
        )
    ) {

        $recaptcha =
            new \ReCaptcha\ReCaptcha(
                $reCaptchaSecret
            );

        $resp =
            $recaptcha->verify(
                $_POST[
                    "g-recaptcha-response"
                ],
                $remoteIp
            );

        return $resp->isSuccess();

    }

    return false;
}


if (
    !validateCaptcha()
) {

    $webpageMessageHeader =
        "reCaptcha validation failed!";

    $webpageMessage =
        "No reCaptcha information found in your request or "
        . "validation failed. You cannot continue to the study. "
        . "Please contact the administrators if this problem persists.";

    $webpageRedirect = False;

    include(
        __DIR__ . "/static/error.php"
    );

    die();
}


try {

    /*
     * Connect to PostgreSQL.
     */
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
     * Connect to Redis.
     */
    $redisConn =
        new Redis();

    $redisConn->connect(
        $redisIp
    );


    /*
     * Check hard study limit.
     */
    if (
        studyLimitReached()
    ) {

        $webpageMessageHeader =
            "Study is over";

        $webpageMessage =
            "Thank you for your interest! "
            . "We have already received the maximum number "
            . "of participants for this study.";

        $webpageRedirect = False;

        include(
            __DIR__ . "/static/error.php"
        );

        die();
    }


    /*
     * Check daily per-IP limit.
     */
    $sth =
        $connect->prepare(
            'SELECT COUNT(*) AS count
             FROM "createdInstances"
             WHERE ip = :ip
               AND time >= NOW() - \'1 day\'::INTERVAL'
        );

    $sth->bindParam(
        ':ip',
        $remoteIp
    );

    $sth->execute();

    $results =
        $sth->fetch(
            PDO::FETCH_ASSOC
        );


    if (
        $results['count']
        < $dailyMaxInstances
    ) {

        $uniqid =
            $token;


        /*
         * Select the least-used internal NERDs
         * task condition.
         *
         * This is separate from the study's
         * AI / NON_AI assignment.
         */
        $sth =
            $connect->prepare(
                'SELECT cond, condcount
                 FROM (
                     SELECT
                         c.condition AS cond,
                         COUNT(ci.condition) AS condcount
                     FROM conditions c
                     LEFT JOIN "createdInstances" ci
                         ON c.condition = ci.condition
                     GROUP BY c.condition
                     ORDER BY RANDOM()
                 ) AS f
                 ORDER BY condcount ASC
                 LIMIT 1;'
            );

        $sth->execute();

        $results =
            $sth->fetch(
                PDO::FETCH_ASSOC
            );


        /*
         * Retrieve category for the selected
         * internal condition.
         */
        $sth =
            $connect->prepare(
                'SELECT category
                 FROM conditions
                 WHERE condition = :condition'
            );

        $sth->bindParam(
            ':condition',
            $results["cond"]
        );

        $sth->execute();

        $resultsCat =
            $sth->fetch(
                PDO::FETCH_ASSOC
            );


        /*
         * Determine whether this participant
         * already exists.
         */
        $sth =
            $connect->prepare(
                'SELECT userid
                 FROM "createdInstances"
                 WHERE userid = :userid;'
            );

        $sth->bindParam(
            ':userid',
            $token
        );

        $sth->execute();

        $resultsUserID =
            $sth->fetch(
                PDO::FETCH_ASSOC
            );

        $existingUserId =
            $resultsUserID[
                'userid'
            ]
            ?? null;


        /*
         * Insert new participant record.
         */
        if (
            $existingUserId
            !== $token
        ) {

            $sth =
                $connect->prepare(
                    'INSERT INTO "createdInstances"
                    (
                        ip,
                        time,
                        origin,
                        userid,
                        condition,
                        category,
                        recruitment_source,
                        prolific_study_id
                    )
                    VALUES
                    (
                        :ip,
                        NOW(),
                        :origin,
                        :userid,
                        :condition,
                        :category,
                        :recruitment_source,
                        :prolific_study_id
                    );'
                );

            $sth->bindParam(
                ':ip',
                $remoteIp
            );

            $sth->bindParam(
                ':userid',
                $token
            );

            $sth->bindValue(
                ':origin',
                $originCode,
                PDO::PARAM_INT
            );

            $sth->bindParam(
                ':condition',
                $results['cond']
            );

            $sth->bindParam(
                ':category',
                $resultsCat['category']
            );

            $sth->bindParam(
                ':recruitment_source',
                $recruitmentSource
            );


            if (
                $prolificStudyId === ""
            ) {

                $sth->bindValue(
                    ':prolific_study_id',
                    null,
                    PDO::PARAM_NULL
                );

            } else {

                $sth->bindParam(
                    ':prolific_study_id',
                    $prolificStudyId
                );
            }


            $sth->execute();

        } else {

            /*
             * Participant already exists.
             *
             * Refresh recruitment metadata so
             * the final-survey handoff remains
             * correct even for a resumed session.
             */
            $sth =
                $connect->prepare(
                    'UPDATE "createdInstances"
                     SET
                         origin = :origin,
                         recruitment_source = :recruitment_source,
                         prolific_study_id = :prolific_study_id
                     WHERE userid = :userid;'
                );

            $sth->bindValue(
                ':origin',
                $originCode,
                PDO::PARAM_INT
            );

            $sth->bindParam(
                ':recruitment_source',
                $recruitmentSource
            );

            $sth->bindParam(
                ':userid',
                $token
            );


            if (
                $prolificStudyId === ""
            ) {

                $sth->bindValue(
                    ':prolific_study_id',
                    null,
                    PDO::PARAM_NULL
                );

            } else {

                $sth->bindParam(
                    ':prolific_study_id',
                    $prolificStudyId
                );
            }


            $sth->execute();
        }


        /*
         * Display study instructions while
         * waiting for an instance.
         */
        include(
            "static/howTo.php"
        );

        ob_flush();
        flush();


        /*
         * Wait for an available NERDs instance.
         */
        $serverToRunOn =
            $redisConn->blPop(
                $redisQueue,
                $waitTimeoutForInstance
            );


        if (
            $serverToRunOn == False
        ) {

            /*
             * Redis did not provide an instance.
             */
            $sth =
                $connect->prepare(
                    'UPDATE "createdInstances"
                     SET
                         ec2instance = :ec2instance,
                         instanceid = :instanceid
                     WHERE userid = :userid;'
                );

            $errorIndicator =
                "error";

            $sth->bindParam(
                ':ec2instance',
                $errorIndicator
            );

            $sth->bindParam(
                ':userid',
                $token
            );

            $sth->bindParam(
                ':instanceid',
                $errorIndicator
            );

            $sth->execute();

        } else {

            /*
             * Redis queue format:
             *
             * container_name|||container_id
             */
            $serverData =
                explode(
                    "|||",
                    $serverToRunOn[1]
                );

            $ec2instance =
                $serverData[0];

            $instanceId =
                $serverData[1];


            /*
             * Associate the participant with
             * the assigned instance.
             */
            $sth =
                $connect->prepare(
                    'UPDATE "createdInstances"
                     SET
                         ec2instance = :ec2instance,
                         instanceid = :instanceid,
                         time = NOW(),
                         heartbeat = NOW(),
                         session_start = NULL,
                         finished = False,
                         "instanceTerminated" = False
                     WHERE userid = :userid;'
                );

            $sth->bindParam(
                ':ec2instance',
                $ec2instance
            );

            $sth->bindParam(
                ':userid',
                $token
            );

            $sth->bindParam(
                ':instanceid',
                $instanceId
            );

            $sth->execute();
        }

    } else {

        $webpageMessageHeader =
            "Error:";

        $webpageMessage =
            "You have already started too many instances. "
            . "Please try again in 24 hours.";

        $webpageRedirect = False;

        include(
            __DIR__ . "/static/error.php"
        );

        die();
    }


} catch (
    PDOException $e
) {

    $webpageMessageHeader =
        "Database error";

    /*
     * Keep existing behavior for now.
     *
     * We should hide detailed exception output
     * before the public launch.
     */
    $webpageMessage =
        $e;

    $webpageRedirect =
        False;

    include(
        __DIR__ . "/static/error.php"
    );

    die();


} catch (
    RedisException $e
) {

    $sth =
        $connect->prepare(
            'UPDATE "createdInstances"
             SET
                 ec2instance = :ec2instance,
                 instanceid = :instanceid
             WHERE userid = :userid;'
        );

    $errorIndicator =
        "error";

    $sth->bindParam(
        ':ec2instance',
        $errorIndicator
    );

    $sth->bindParam(
        ':userid',
        $token
    );

    $sth->bindParam(
        ':instanceid',
        $errorIndicator
    );

    $sth->execute();

    die();
}

?>
