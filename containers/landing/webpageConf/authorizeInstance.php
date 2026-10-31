<?php
declare(strict_types=1);

require_once __DIR__ . '/config.php';

header('Cache-Control: no-store');
header('Content-Length: 0');

$token = $_COOKIE['__Host-nerds_session'] ?? '';
$originalUri = $_SERVER['STUDY_ORIGINAL_URI'] ?? '';

if (!is_string($token) ||
    !preg_match('/^[a-f0-9]{64}$/D', $token)) {
    http_response_code(401);
    exit;
}

$path = is_string($originalUri)
    ? parse_url($originalUri, PHP_URL_PATH)
    : false;

if (!is_string($path) ||
    !preg_match('~\A/proxy/([a-f0-9]{12})(?:/|\z)~', $path, $matches)) {
    http_response_code(403);
    exit;
}

$instanceId = $matches[1];
$secretHash = hash('sha256', $token);

try {
    $pdo = new PDO(
        "pgsql:host=$dbhost;dbname=$dbname",
        $dbuser,
        $dbpass,
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );

    $stmt = $pdo->prepare('
        SELECT 1
        FROM fuzz_pilot.auth_sessions AS auth
        JOIN fuzz_pilot.study_sessions AS study
            ON study.session_id = auth.session_id
        JOIN fuzz_pilot.participants AS participant
            ON participant.participant_id = study.participant_id
        WHERE auth.secret_sha256 = :secret_hash
          AND auth.revoked_at IS NULL
          AND auth.expires_at > NOW()
          AND study.instance_id = :instance_id
          AND study.status = \'active\'
          AND study.howto_acknowledged_at IS NOT NULL
          AND participant.withdrawn_at IS NULL
        LIMIT 1
    ');

    $stmt->execute([
        ':secret_hash' => $secretHash,
        ':instance_id' => $instanceId
    ]);

    http_response_code($stmt->fetchColumn() !== false ? 204 : 403);

} catch (Throwable $e) {
    error_log('NERDs authorization database failure: ' . $e->getMessage());
    http_response_code(503);
}
