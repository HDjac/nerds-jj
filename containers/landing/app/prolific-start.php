<?php

require_once(__DIR__ . "/../webpageConf/config.php");
require_once('util.php');


$csvFile =
    "/study-data/participant_assignments.csv";

$lockFile =
    "/study-data/participant_assignments.lock";

$configFile =
    "/study-data/prolific_main_config.json";

$allowlistFile =
    "/study-data/prolific_main_allowlist.txt";


$MIN_ID = 1;
$MAX_ID = 1023;

$AI_CONDITION = "AI";
$NON_AI_CONDITION = "NON_AI";


function showError($message) {

    $webpageMessageHeader =
        "Study start error";

    $webpageMessage =
        htmlspecialchars(
            $message,
            ENT_QUOTES,
            "UTF-8"
        );

    $webpageRedirect = False;

    include(
        __DIR__
        . "/static/error.php"
    );

    die();
}


function readConfig($path) {

    if (!file_exists($path)) {

        throw new Exception(
            "Prolific study configuration "
            . "is not available."
        );
    }

    $raw =
        file_get_contents(
            $path
        );

    if ($raw === false) {

        throw new Exception(
            "Could not read Prolific "
            . "study configuration."
        );
    }

    $config =
        json_decode(
            $raw,
            true
        );

    if (!is_array($config)) {

        throw new Exception(
            "Invalid Prolific "
            . "study configuration."
        );
    }

    return $config;
}


function readAllowlist($path) {

    if (!file_exists($path)) {

        throw new Exception(
            "Prolific participant "
            . "allowlist is not available."
        );
    }

    $lines =
        file(
            $path,
            FILE_IGNORE_NEW_LINES
            | FILE_SKIP_EMPTY_LINES
        );

    if ($lines === false) {

        throw new Exception(
            "Could not read Prolific "
            . "participant allowlist."
        );
    }

    $allowed = [];

    foreach ($lines as $line) {

        $line =
            trim($line);

        if (
            $line === ""
            || substr(
                $line,
                0,
                1
            ) === "#"
        ) {

            continue;
        }

        $allowed[
            strtolower($line)
        ] = true;
    }

    return $allowed;
}


function validateProlificValue(
    $value,
    $name
) {

    $value =
        trim(
            (string)$value
        );

    if ($value === "") {

        throw new Exception(
            "Missing "
            . $name
            . "."
        );
    }

    if (
        !preg_match(
            '/^[A-Za-z0-9_-]{6,128}$/',
            $value
        )
    ) {

        throw new Exception(
            "Invalid "
            . $name
            . "."
        );
    }

    return $value;
}


function normalizeBoolean(
    $value
) {

    $value =
        strtolower(
            trim(
                (string)$value
            )
        );

    return in_array(
        $value,
        [
            "1",
            "true",
            "yes",
            "y"
        ],
        true
    );
}


function normalizeStudyConfig(
    $config
) {

    $studies =
        $config[
            "studies"
        ]
        ?? [];

    if (!is_array($studies)) {

        throw new Exception(
            "Prolific studies "
            . "configuration is invalid."
        );
    }

    $required = [
        "developer",
        "non_developer"
    ];

    $normalized = [];

    foreach (
        $required
        as $studyType
    ) {

        $studyId =
            validateProlificValue(
                $studies[
                    $studyType
                ]
                ?? "",
                $studyType
                . " Prolific study ID"
            );

        $normalized[
            $studyType
        ] =
            strtolower(
                $studyId
            );
    }

    if (
        hash_equals(
            $normalized[
                "developer"
            ],
            $normalized[
                "non_developer"
            ]
        )
    ) {

        throw new Exception(
            "Developer and non-developer "
            . "Prolific study IDs must differ."
        );
    }

    return $normalized;
}


function identifyStudyType(
    $studyId,
    $configuredStudies
) {

    $studyId =
        strtolower(
            trim(
                (string)$studyId
            )
        );

    foreach (
        $configuredStudies
        as $studyType
            => $expectedStudyId
    ) {

        if (
            hash_equals(
                $expectedStudyId,
                $studyId
            )
        ) {

            return $studyType;
        }
    }

    return null;
}


function readAssignments(
    $csvFile
) {

    $rows = [];

    clearstatcache(
        true,
        $csvFile
    );

    if (
        !file_exists(
            $csvFile
        )
        || filesize(
            $csvFile
        ) === 0
    ) {

        return $rows;
    }

    $file =
        fopen(
            $csvFile,
            "r"
        );

    if ($file === false) {

        throw new Exception(
            "Could not open assignment "
            . "CSV for reading."
        );
    }

    $header =
        fgetcsv($file);

    if ($header === false) {

        fclose($file);

        return $rows;
    }

    $required = [
        "identifier",
        "participant_id",
        "developer",
        "condition",
        "assigned_at"
    ];

    foreach (
        $required
        as $field
    ) {

        if (
            array_search(
                $field,
                $header,
                true
            ) === false
        ) {

            fclose($file);

            throw new Exception(
                "Assignment CSV is missing "
                . "required field: "
                . $field
            );
        }
    }

    while (
        (
            $data =
                fgetcsv($file)
        ) !== false
    ) {

        $row = [];

        foreach (
            $header
            as $index => $field
        ) {

            $row[
                $field
            ] =
                $data[
                    $index
                ]
                ?? "";
        }

        $rows[] =
            $row;
    }

    fclose($file);

    return $rows;
}


function findExistingAssignment(
    $identifier,
    $rows
) {

    $needle =
        strtolower(
            trim(
                $identifier
            )
        );

    foreach (
        $rows
        as $row
    ) {

        $candidate =
            strtolower(
                trim(
                    $row[
                        "identifier"
                    ]
                    ?? ""
                )
            );

        if (
            $candidate
            === $needle
        ) {

            return $row;
        }
    }

    return null;
}


function collectExistingIds(
    $rows
) {

    $ids = [];

    foreach (
        $rows
        as $row
    ) {

        $rawId =
            trim(
                $row[
                    "participant_id"
                ]
                ?? ""
            );

        if (
            ctype_digit(
                $rawId
            )
        ) {

            $ids[
                (int)$rawId
            ] = true;
        }
    }

    return $ids;
}


function generateParticipantId(
    $existingIds,
    $requiredParity = null
) {

    global $MIN_ID;
    global $MAX_ID;

    $available = [];

    for (
        $id = $MIN_ID;
        $id <= $MAX_ID;
        $id++
    ) {

        if (
            isset(
                $existingIds[
                    $id
                ]
            )
        ) {

            continue;
        }

        if (
            $requiredParity !== null
            && (
                $id % 2
            ) !== $requiredParity
        ) {

            continue;
        }

        $available[] =
            $id;
    }

    if (
        count(
            $available
        ) === 0
    ) {

        throw new Exception(
            "No unused participant IDs "
            . "remain for this cohort."
        );
    }

    return $available[
        random_int(
            0,
            count(
                $available
            ) - 1
        )
    ];
}


function conditionForParticipantId(
    $participantId
) {

    global $AI_CONDITION;
    global $NON_AI_CONDITION;

    return (
        (
            (int)$participantId
            % 2
        ) === 0
    )
        ? $AI_CONDITION
        : $NON_AI_CONDITION;
}


function appendAssignment(
    $csvFile,
    $assignment
) {

    clearstatcache(
        true,
        $csvFile
    );

    $fileExists =
        file_exists(
            $csvFile
        );

    $fileEmpty =
        !$fileExists
        || filesize(
            $csvFile
        ) === 0;

    $file =
        fopen(
            $csvFile,
            "a"
        );

    if ($file === false) {

        throw new Exception(
            "Could not open assignment "
            . "CSV for writing."
        );
    }

    if ($fileEmpty) {

        fputcsv(
            $file,
            [
                "identifier",
                "participant_id",
                "developer",
                "condition",
                "assigned_at"
            ]
        );
    }

    fputcsv(
        $file,
        [
            $assignment[
                "identifier"
            ],
            $assignment[
                "participant_id"
            ],
            $assignment[
                "developer"
            ],
            $assignment[
                "condition"
            ],
            $assignment[
                "assigned_at"
            ]
        ]
    );

    fflush($file);

    if (
        function_exists(
            "fsync"
        )
    ) {

        fsync($file);
    }

    fclose($file);
}


function buildConsentUrl(
    $baseUrl,
    $participantId,
    $prolificPid,
    $studyId,
    $sessionId
) {

    $separator =
        strpos(
            $baseUrl,
            "?"
        ) === false
        ? "?"
        : "&";

    /*
     * QuestionPro System Variable Mapping:
     *
     * Custom 1 -> participant_id
     * Custom 2 -> prolific_pid
     * Custom 3 -> prolific_study_id
     * Custom 4 -> prolific_session_id
     * Custom 5 -> origin
     */
    $query =
        http_build_query(
            [
                "participant_id"
                    => $participantId,

                "prolific_pid"
                    => $prolificPid,

                "prolific_study_id"
                    => $studyId,

                "prolific_session_id"
                    => $sessionId,

                "origin"
                    => "prolific"
            ],
            "",
            "&",
            PHP_QUERY_RFC3986
        );

    return (
        $baseUrl
        . $separator
        . $query
    );
}


try {

    $config =
        readConfig(
            $configFile
        );


    /*
     * Master switch.
     */
    $enabled =
        filter_var(
            $config[
                "enabled"
            ]
            ?? false,
            FILTER_VALIDATE_BOOLEAN
        );

    if (!$enabled) {

        throw new Exception(
            "The Prolific main study "
            . "is not currently open."
        );
    }


    /*
     * When true, only PIDs listed in
     * prolific_main_allowlist.txt may enter.
     *
     * It defaults to TRUE if the configuration
     * option is missing. This keeps the safer
     * historical behavior unless production
     * explicitly disables the allowlist.
     */
    $requireAllowlist =
        filter_var(
            $config[
                "require_allowlist"
            ]
            ?? true,
            FILTER_VALIDATE_BOOLEAN
        );


    $configuredStudies =
        normalizeStudyConfig(
            $config
        );


    $consentUrl =
        trim(
            (string)(
                $config[
                    "consent_url"
                ]
                ?? ""
            )
        );

    if (
        $consentUrl === ""
    ) {

        throw new Exception(
            "Consent URL "
            . "is not configured."
        );
    }


    /*
     * Values supplied by Prolific.
     */
    $prolificPid =
        validateProlificValue(
            $_GET[
                "PROLIFIC_PID"
            ]
            ?? "",
            "Prolific participant ID"
        );

    $studyId =
        validateProlificValue(
            $_GET[
                "STUDY_ID"
            ]
            ?? "",
            "Prolific study ID"
        );

    $sessionId =
        validateProlificValue(
            $_GET[
                "SESSION_ID"
            ]
            ?? "",
            "Prolific session ID"
        );


    /*
     * Reject links that are not for one of the
     * configured Prolific studies.
     */
    $studyType =
        identifyStudyType(
            $studyId,
            $configuredStudies
        );

    if (
        $studyType === null
    ) {

        throw new Exception(
            "This link is not for "
            . "an active Prolific study."
        );
    }


    $isDeveloper =
        (
            $studyType
            === "developer"
        );


    /*
     * Optional controlled-test allowlist.
     *
     * Production:
     *     require_allowlist = false
     *
     * Controlled testing:
     *     require_allowlist = true
     */
    if ($requireAllowlist) {

        $allowlist =
            readAllowlist(
                $allowlistFile
            );

        if (
            !isset(
                $allowlist[
                    strtolower(
                        $prolificPid
                    )
                ]
            )
        ) {

            throw new Exception(
                "This Prolific participant "
                . "is not currently authorized "
                . "for the main study."
            );
        }
    }


    /*
     * Serialize assignment generation so two
     * participants cannot receive the same
     * NERDs participant ID.
     */
    $lock =
        fopen(
            $lockFile,
            "c+"
        );

    if ($lock === false) {

        throw new Exception(
            "Could not open participant "
            . "assignment lock."
        );
    }

    if (
        !flock(
            $lock,
            LOCK_EX
        )
    ) {

        fclose($lock);

        throw new Exception(
            "Could not lock participant "
            . "assignments."
        );
    }


    try {

        $rows =
            readAssignments(
                $csvFile
            );

        $existing =
            findExistingAssignment(
                $prolificPid,
                $rows
            );


        /*
         * Reuse an existing assignment when the
         * same Prolific participant returns.
         */
        if (
            $existing !== null
        ) {

            $participantId =
                trim(
                    $existing[
                        "participant_id"
                    ]
                    ?? ""
                );

            if (
                !ctype_digit(
                    $participantId
                )
            ) {

                throw new Exception(
                    "Existing participant "
                    . "assignment is invalid."
                );
            }

            $existingDeveloper =
                normalizeBoolean(
                    $existing[
                        "developer"
                    ]
                    ?? ""
                );

            $existingCondition =
                strtoupper(
                    trim(
                        $existing[
                            "condition"
                        ]
                        ?? ""
                    )
                );

            $expectedCondition =
                conditionForParticipantId(
                    $participantId
                );


            if (
                $existingDeveloper
                !== $isDeveloper
            ) {

                throw new Exception(
                    "Existing assignment does "
                    . "not match this Prolific "
                    . "study cohort."
                );
            }


            if (
                $existingCondition
                !== $expectedCondition
            ) {

                throw new Exception(
                    "Existing participant "
                    . "condition does not match "
                    . "participant ID parity."
                );
            }


            if (
                !$isDeveloper
                && $existingCondition
                    !== "AI"
            ) {

                throw new Exception(
                    "Existing assignment does "
                    . "not match the Prolific "
                    . "non-developer cohort."
                );
            }


        } else {

            $existingIds =
                collectExistingIds(
                    $rows
                );


            if ($isDeveloper) {

                /*
                 * Developer cohort:
                 *
                 * even PID = AI
                 * odd PID  = NON_AI
                 */
                $participantId =
                    (string)
                    generateParticipantId(
                        $existingIds
                    );

                $condition =
                    conditionForParticipantId(
                        $participantId
                    );

                $developerValue =
                    "1";


            } else {

                /*
                 * Non-developer cohort:
                 *
                 * Always AI, therefore always
                 * allocate an unused even PID.
                 */
                $participantId =
                    (string)
                    generateParticipantId(
                        $existingIds,
                        0
                    );

                $condition =
                    "AI";

                $developerValue =
                    "0";
            }


            appendAssignment(
                $csvFile,
                [
                    "identifier"
                        => $prolificPid,

                    "participant_id"
                        => $participantId,

                    "developer"
                        => $developerValue,

                    "condition"
                        => $condition,

                    "assigned_at"
                        => gmdate("c")
                ]
            );
        }


    } finally {

        flock(
            $lock,
            LOCK_UN
        );

        fclose($lock);
    }


    /*
     * Hand the assigned participant to the
     * QuestionPro consent survey.
     */
    $destination =
        buildConsentUrl(
            $consentUrl,
            $participantId,
            $prolificPid,
            $studyId,
            $sessionId
        );

    header(
        "Location: "
        . $destination,
        true,
        302
    );

    exit();


} catch (Throwable $e) {

    showError(
        $e->getMessage()
    );
}

?>
