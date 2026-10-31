<?php
declare(strict_types=1);
require_once __DIR__ . '/../webpageConf/pilot1OnboardingLib.php';
nerds_onboarding_headers();
try {
    $pdo = nerds_onboarding_db();
    $state = nerds_onboarding_context($pdo);
    if ($state['howto_done']) nerds_onboarding_workspace($state);
    if ($state['intro_done']) nerds_onboarding_redirect('/pilot1-howto.php');
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
        nerds_onboarding_verify_post($state, 'intro');
        nerds_onboarding_advance($pdo, $state, 'intro');
        nerds_onboarding_redirect('/pilot1-howto.php');
    }
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') nerds_onboarding_fail(405);
} catch (Throwable $e) {
    error_log('NERDs intro onboarding failure: ' . get_class($e));
    nerds_onboarding_fail(503);
}
?>
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NERDs — Introduction</title><style>
body{font:16px/1.6 system-ui,sans-serif;max-width:850px;margin:2rem auto;padding:0 1.25rem;color:#222}
h1{font-size:1.8rem} button{font:inherit;background:#174b7c;color:white;border:0;border-radius:.4rem;padding:.75rem 1.2rem;cursor:pointer}
li{margin:.6rem 0} .note{border-left:4px solid #174b7c;padding:.6rem 1rem;background:#f4f7fa}
</style></head><body><main>
<h1>Introduction — NERDs Fuzzing Study</h1>
<p>You'll investigate <strong>two C programs</strong> using coverage-guided fuzzing in an isolated workspace. Each task provides source code, fuzzing harnesses, and a terminal.</p>
<p>Use the <strong>CLI</strong> to inspect, edit, compile and fuzz. Use the internal <strong>BROWSER</strong> tab for study-related research and AI tools when allowed by your study instructions.</p>
<ul><li>You can start, stop and resume fuzzing campaigns.</li><li>Choose <strong>Finish Task</strong> when you believe you're done, or <strong>Skip Task</strong> to stop early. Either choice records your work.</li><li>You can't return to a previous task after moving on.</li><li>Use the <strong>View Fuzzing Guide</strong> button in either task if you need help.</li></ul>
<p class="note">The next page explains the commands you need. Please review it before starting Task 1. Follow the consent information provided by your research team; this introduction does not replace consent.</p>
<form method="post" action="/pilot1-intro.php"><input type="hidden" name="csrf" value="<?= htmlspecialchars(nerds_onboarding_csrf($state['cookie'], 'intro'), ENT_QUOTES, 'UTF-8') ?>"><button type="submit">Continue to Fuzzing Guide</button></form>
</main></body></html>
