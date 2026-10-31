<?php
declare(strict_types=1);
require_once __DIR__ . '/../webpageConf/pilot1OnboardingLib.php';
nerds_onboarding_headers();
try {
    $pdo = nerds_onboarding_db();
    $state = nerds_onboarding_context($pdo);
    if (!$state['intro_done']) nerds_onboarding_redirect('/pilot1-intro.php');
    if ($state['howto_done']) nerds_onboarding_workspace($state);
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
        nerds_onboarding_verify_post($state, 'howto');
        if (($_POST['reviewed'] ?? '') !== '1') nerds_onboarding_fail(400);
        nerds_onboarding_advance($pdo, $state, 'howto');
        nerds_onboarding_workspace($state);
    }
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') nerds_onboarding_fail(405);
} catch (Throwable $e) {
    error_log('NERDs howto onboarding failure: ' . get_class($e));
    nerds_onboarding_fail(503);
}
?>
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NERDs — Required Fuzzing Guide</title><style>
body{font:16px/1.55 system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1.25rem;color:#222}
pre{overflow:auto;background:#f1f3f6;padding:1rem;border-radius:.4rem}code{font:14px/1.5 ui-monospace,Consolas,monospace}
h1{font-size:1.8rem}h2{margin-top:2rem}li{margin:.7rem 0}button{font:inherit;background:#174b7c;color:white;border:0;border-radius:.4rem;padding:.75rem 1.2rem;cursor:pointer}
</style></head><body><main>
<h1>Required HowTo — Fuzzing Guide</h1><p>Review how to compile, start, stop, and continue fuzzing. The guide is also available from the task sidebar.</p>
<?php require __DIR__ . '/static/fuzzing-guide-content.php'; ?>
<hr><form method="post" action="/pilot1-howto.php"><input type="hidden" name="csrf" value="<?= htmlspecialchars(nerds_onboarding_csrf($state['cookie'], 'howto'), ENT_QUOTES, 'UTF-8') ?>">
<p><label><input type="checkbox" name="reviewed" value="1" required> I have reviewed the fuzzing instructions.</label></p>
<button type="submit">Start Study</button></form>
</main></body></html>
