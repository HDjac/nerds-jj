<?php
declare(strict_types=1);

header('Cache-Control: no-store, max-age=0');
header('Pragma: no-cache');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header('Content-Type: application/json; charset=utf-8');
header('X-Frame-Options: DENY');

function fail_redeem(int $status, string $message): never {
    http_response_code($status);
    echo json_encode(['error' => $message], JSON_THROW_ON_ERROR);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    fail_redeem(405, 'Method not allowed');
}

// Reject cross-site browser requests. The browser login page sends this
// non-simple custom header, and the endpoint does not enable CORS.
if (($_SERVER['HTTP_X_NERDS_INVITATION'] ?? '') !== '1'
    || !str_starts_with(strtolower((string) ($_SERVER['CONTENT_TYPE'] ?? '')), 'application/json')) {
    fail_redeem(400, 'Invalid request');
}

// Make sure the public endpoint is served on HTTPS, not the HTTP redirect port.
if (!in_array(strtolower((string) ($_SERVER['HTTPS'] ?? '')), ['on', '1'], true)) {
    fail_redeem(403, 'HTTPS required');
}

$body = file_get_contents('php://input', false, null, 0, 1025);
if (!is_string($body) || strlen($body) > 1024) {
    fail_redeem(400, 'Invalid request');
}

try {
    $data = json_decode($body, true, 4, JSON_THROW_ON_ERROR);
} catch (JsonException $e) {
    fail_redeem(400, 'Invalid request');
}

if (!is_array($data) || !isset($data['token']) || !is_string($data['token'])
    || preg_match('/^[a-f0-9]{64}$/D', $data['token']) !== 1) {
    fail_redeem(400, 'Invalid invitation');
}

$invitationDigest = hash('sha256', $data['token']);
$browserSecret = bin2hex(random_bytes(32));
$browserDigest = hash('sha256', $browserSecret);
$browserMinutes = 120;

try {
    require_once __DIR__ . '/../webpageConf/config.php';

    $pdo = new PDO(
        "pgsql:host=$dbhost;dbname=$dbname",
        $dbuser,
        $dbpass,
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );

    $stmt = $pdo->prepare(
        'SELECT instance_id, auth_session_id '
        . 'FROM fuzz_pilot.redeem_pilot1_invitation(:invitation, :browser, :minutes)'
    );
    $stmt->bindValue(':invitation', $invitationDigest, PDO::PARAM_STR);
    $stmt->bindValue(':browser', $browserDigest, PDO::PARAM_STR);
    $stmt->bindValue(':minutes', $browserMinutes, PDO::PARAM_INT);
    $stmt->execute();
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!is_array($row)) {
        fail_redeem(410, 'Invitation expired or already used');
    }
    $instance = $row['instance_id'] ?? '';
    if (!is_string($instance) || preg_match('/^[a-f0-9]{12}$/D', $instance) !== 1) {
        throw new RuntimeException('Invalid assigned instance');
    }
    if (!setcookie('__Host-nerds_session', $browserSecret, [
        'expires' => time() + $browserMinutes * 60,
        'path' => '/',
        'secure' => true,
        'httponly' => true,
        'samesite' => 'Lax'
    ])) {
        throw new RuntimeException('Failed to send session cookie');
    }
    http_response_code(200);
    echo json_encode(['redirect' => '/pilot1-intro.php'], JSON_THROW_ON_ERROR);
} catch (Throwable $e) {
    // Do not leak DB errors or secret values to browsers or access logs.
    error_log('Pilot 1 redemption failed: ' . get_class($e));
    fail_redeem(503, 'Invitation service unavailable');
}
