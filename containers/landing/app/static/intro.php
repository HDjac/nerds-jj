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

    </div>
</div>
<form id="continue_form" method="post" action="howTo.php">
    <div id="recaptcha" class="g-recaptcha"
    data-sitekey="<?php echo $reCaptchaSiteKey; ?>"
    data-size="invisible"
    data-callback="onReCaptcha"
    ></div>
    <input type="hidden" id="pid" name="pid" value="<?php echo $pid ?>">
    <input type="hidden" id="origin" name="origin" value="<?php echo $originParam ?>">
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

<html>
