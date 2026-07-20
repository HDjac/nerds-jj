<!DOCTYPE html>
<html lang="en">

<?php $title="Study - Introduction"; include('template/head.php'); ?>

<?php include('template/body.html') ?>

<hr class="featurette-divider">
<div class="row">
    <div class="col-lg-6"  style="text-align: justify;">
        <p><h2>Introduction</h2></p>

        <p>
        This study examines how people complete secure software development tasks using different resources.
        You will complete three short programming tasks in C.
        </p>

        <p>The three tasks involve:</p>
        <ul>
            <li>Reading code and adding comments that identify correctness or security issues</li>
            <li>Fixing existing code so it is functionally correct and secure</li>
            <li>Writing a small function from scratch</li>
        </ul>

        <p>
        As you work, consider whether the code handles user input correctly, avoids unsafe assumptions,
        and behaves securely for unexpected or malicious input.
        </p>

        <p><b>You will have 60 minutes to complete all tasks.</b></p>

        <p><strong>Testing AI group:</strong> <?= htmlspecialchars($aiGroup, ENT_QUOTES, "UTF-8") ?></p>
    </div>
</div>
<form id="continue_form" method="post" action="howTo.php">
    <div id="recaptcha" class="g-recaptcha"
    data-sitekey="<?php echo $reCaptchaSiteKey; ?>"
    data-size="invisible"
    data-callback="onReCaptcha"
    ></div>
    <input type="hidden" id="pid" name="pid" value="<?= htmlspecialchars($pid, ENT_QUOTES, "UTF-8") ?>">
    <input type="hidden" id="ext_ref" name="ext_ref" value="<?= htmlspecialchars($pid, ENT_QUOTES, "UTF-8") ?>">
    <input type="hidden" id="origin" name="origin" value="<?= htmlspecialchars($originParam, ENT_QUOTES, "UTF-8") ?>">
    <input type="hidden" id="ai_group" name="ai_group" value="<?= htmlspecialchars($aiGroup, ENT_QUOTES, "UTF-8") ?>">
    <button type="submit" class="btn btn-default" id="submit-btn">Continue</button>
</form>

<hr class="featurette-divider">

<?php include('template/bodyend.html') ?>

<script type="text/javascript">
  $("#submit-btn").click((e) => {
    grecaptcha.execute();
    e.preventDefault();
  });

  function onReCaptcha(resp) {
      $("#continue_form")[0].submit();
  }
</script>

<script src="https://www.google.com/recaptcha/api.js" async defer></script>

</html>
