<?php

require_once(
    __DIR__
    . "/../webpageConf/config.php"
);

require_once(
    'util.php'
);

$csvFile =
    "/study-data/participant_assignments.csv";

$prolificConfigFile =
    "/study-data/prolific_main_config.json";


function participantExists(
    $csvFile,
    $participantId
) {

    if (
        !file_exists($csvFile)
        || filesize($csvFile) === 0
    ) {

        return false;
    }

    $file =
        fopen(
            $csvFile,
            "r"
        );

    if ($file === false) {

        return false;
    }

    $header =
        fgetcsv($file);

    if ($header === false) {

        fclose($file);

        return false;
    }

    $pidIndex =
        array_search(
            "participant_id",
            $header,
            true
        );

    if ($pidIndex === false) {

        fclose($file);

        return false;
    }

    while (
        (
            $data =
                fgetcsv($file)
        ) !== false
    ) {

        $rowPid =
            trim(
                $data[
                    $pidIndex
                ]
                ?? ""
            );

        if (
            $rowPid
            === $participantId
        ) {

            fclose($file);

            return true;
        }
    }

    fclose($file);

    return false;
}


function readProlificConfig(
    $path
) {

    if (
        !file_exists($path)
    ) {

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

    if (
        !is_array($config)
    ) {

        throw new Exception(
            "Invalid Prolific "
            . "study configuration."
        );
    }

    return $config;
}


function validateProlificStudyId(
    $studyId,
    $config
) {

    $studyId =
        trim(
            (string)$studyId
        );

    if ($studyId === "") {

        throw new Exception(
            "Missing Prolific study ID."
        );
    }

    if (
        !preg_match(
            '/^[A-Za-z0-9_-]{6,128}$/',
            $studyId
        )
    ) {

        throw new Exception(
            "Invalid Prolific study ID."
        );
    }

    $studies =
        $config[
            "studies"
        ]
        ?? [];

    if (
        !is_array($studies)
    ) {

        throw new Exception(
            "Prolific studies "
            . "configuration is invalid."
        );
    }

    foreach (
        $studies
        as $expectedStudyId
    ) {

        $expectedStudyId =
            trim(
                (string)$expectedStudyId
            );

        if (
            $expectedStudyId !== ""
            && hash_equals(
                strtolower(
                    $expectedStudyId
                ),
                strtolower(
                    $studyId
                )
            )
        ) {

            return $studyId;
        }
    }

    throw new Exception(
        "This Prolific study ID "
        . "is not recognized."
    );
}


try {

    $participantId =
        trim(
            $_GET[
                "participant_id"
            ]
            ?? $_GET[
                "ext_ref"
            ]
            ?? ""
        );

    if (
        $participantId === ""
    ) {

        throw new Exception(
            "Missing participant ID."
        );
    }

    if (
        !preg_match(
            '/^\d+$/',
            $participantId
        )
    ) {

        throw new Exception(
            "Invalid participant ID."
        );
    }

    if (
        !participantExists(
            $csvFile,
            $participantId
        )
    ) {

        throw new Exception(
            "Participant ID was not found "
            . "in the assignment file."
        );
    }

    /*
     * Recruitment source.
     *
     * Prolific consent responses send:
     *
     * origin=prolific
     *
     * Other/older study flows may omit
     * this parameter.
     */

    $origin =
        trim(
            (string)(
                $_GET[
                    "origin"
                ]
                ?? ""
            )
        );

    if ($origin === "") {

        $origin = "legacy";
    }

    if (
        !preg_match(
            '/^[A-Za-z0-9_-]{1,32}$/',
            $origin
        )
    ) {

        throw new Exception(
            "Invalid recruitment source."
        );
    }

    /*
     * Only Prolific participants need
     * a Prolific study ID.
     */

    $prolificStudyId = "";

    if (
        strtolower($origin)
        === "prolific"
    ) {

        $config =
            readProlificConfig(
                $prolificConfigFile
            );

        $prolificStudyId =
            validateProlificStudyId(
                $_GET[
                    "prolific_study_id"
                ]
                ?? "",
                $config
            );
    }

    $queryParams = [
        "ext_ref"
            => $participantId,

        "origin"
            => $origin
    ];

    if (
        $prolificStudyId !== ""
    ) {

        $queryParams[
            "prolific_study_id"
        ] =
            $prolificStudyId;
    }

    $destination =
        "/index.php?"
        . http_build_query(
            $queryParams,
            "",
            "&",
            PHP_QUERY_RFC3986
        );

    header(
        "Location: "
        . $destination,
        true,
        302
    );

    exit();

} catch (
    Throwable $e
) {

    $webpageMessageHeader =
        "Study start error";

    $webpageMessage =
        htmlspecialchars(
            $e->getMessage(),
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

?>
