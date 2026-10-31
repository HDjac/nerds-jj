<?php
declare(strict_types=1);
// Shared, non-web-accessible authorization helper for the Pilot 1 onboarding pages.
// User-controlled paths, participant IDs and instance IDs are NEVER accepted here.
require_once __DIR__ . '/config.php';

function nerds_onboarding_headers(): void {
    header('Cache-Control: no-store, max-age=0');
    header('Pragma: no-cache');
    header('Referrer-Policy: no-referrer');
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header("Content-Security-Policy: default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; style-src 'unsafe-inline'");
}
function nerds_onboarding_fail(int $code = 403): never {
    http_response_code($code);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Study authorization is unavailable or expired. Request a fresh invitation from the study administrator.';
    exit;
}
function nerds_onboarding_db(): PDO {
    global $dbhost, $dbname, $dbuser, $dbpass;
    return new PDO("pgsql:host=$dbhost;dbname=$dbname", $dbuser, $dbpass,
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
}
function nerds_onboarding_context(PDO $pdo): array {
    $cookie = $_COOKIE['__Host-nerds_session'] ?? null;
    if (!is_string($cookie) || preg_match('/^[a-f0-9]{64}$/D', $cookie) !== 1) {
        nerds_onboarding_fail(401);
    }
    $digest = hash('sha256', $cookie);
    // Database function derives the study and instance from a valid, active auth session.
    $stmt = $pdo->prepare('SELECT instance_id, intro_done, howto_done FROM fuzz_pilot.pilot1_onboarding_state(:digest)');
    $stmt->execute([':digest' => $digest]);
    $state = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!is_array($state) || !is_string($state['instance_id']) ||
        preg_match('/^[a-f0-9]{12}$/D', $state['instance_id']) !== 1) {
        nerds_onboarding_fail(403);
    }
    $state['intro_done'] = in_array($state['intro_done'], [true, 't', '1', 1], true);
    $state['howto_done'] = in_array($state['howto_done'], [true, 't', '1', 1], true);
    $state['cookie'] = $cookie; // local only; never echo or log
    $state['digest'] = $digest;
    return $state;
}
function nerds_onboarding_csrf(string $cookie, string $step): string {
    return hash_hmac('sha256', 'pilot1-onboarding:v1:' . $step, $cookie);
}
function nerds_onboarding_verify_post(array $state, string $step): void {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') nerds_onboarding_fail(405);
    $submitted = $_POST['csrf'] ?? null;
    if (!is_string($submitted) || !hash_equals(
        nerds_onboarding_csrf($state['cookie'], $step), $submitted)) {
        nerds_onboarding_fail(403);
    }
}
function nerds_onboarding_advance(PDO $pdo, array $state, string $step): void {
    $stmt = $pdo->prepare('SELECT fuzz_pilot.advance_pilot1_onboarding(:digest, :step)');
    $stmt->execute([':digest' => $state['digest'], ':step' => $step]);
    $result = $stmt->fetchColumn();
    if ($result !== 't' && $result !== true && $result !== '1') nerds_onboarding_fail(403);
}
function nerds_onboarding_redirect(string $path): never {
    header('Location: ' . $path, true, 303);
    exit;
}
function nerds_onboarding_workspace(array $state): never {
    nerds_onboarding_redirect('/proxy/' . $state['instance_id'] . '/');
}
