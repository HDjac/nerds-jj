<!DOCTYPE html>
<html lang="en">

<?php $title="Study - How To"; include('template/head.php'); ?>

<?php include('template/body.html') ?>

<hr class="featurette-divider">
<div class="row">
    <div class="col-lg-6" style="text-align: justify;">


<h2>Study Instructions</h2>

<p>
For this study, you will be tasked with completing three C programming tasks. The tasks will appear in a random order. 
You will need to use the online editor and built-in browser that you can access below. 
</p>

<ul>
  <li><b>Read task:</b> Read existing code and add inline comments identifying correctness or security issues.</li>
  <li><b>Fix task:</b> Modify existing code so it is functionally correct and secure.</li>
  <li><b>Write task:</b> Write a small C function from scratch that satisfies the stated requirements.</li>
</ul></p>

<p>
    For all tasks, consider whether the code correctly handles user input, accepts only valid usernames,
    rejects invalid or overly long input, and avoids unsafe behavior.
</p>

<h2>Using the Interface</h2>

<p>
The study environment has two main tabs:
</p>

<ul>
  <li><b>Code tab:</b> Use this tab to read, edit, comment on, or write code.</li>
  <li><b>Browser tab:</b> Use this built-in browser for any web resources you need during the study.</li>
</ul>

<p>
Please use only the built-in browser for study-related web access. Copying and pasting from outside the
study environment is restricted. Copying and pasting within the study environment may be allowed.
</p>

<h2>Task Navigation</h2>

<p>
Once you click <b>Next Task</b> or <b>Skip Task</b>, you will not be able to return to that task.
Please make sure you are ready before moving on.
</p>

<p>
If you are unable to complete a task, click <b>Skip Task</b>. We still appreciate your effort.
</p>

<h2>AI Tool Use</h2>

<?php if (isset($aiGroup) && $aiGroup === "AI"): ?>
    <p>
        You are assigned to the <b>AI</b> condition. You may use the built-in browser
        and AI tools available inside the study environment while completing the tasks.
        Do not use tools outside the study environment.
    </p>
<?php elseif (isset($aiGroup) && $aiGroup === "NON_AI"): ?>
    <p>
        You are assigned to the <b>Non-AI</b> condition. You may use the built-in browser for
        documentation and web searches, but you may not use AI assistants, including ChatGPT,
        Copilot, Gemini, Claude, or similar tools.
    </p>

    <p>
        <b>Using AI tools when they are not allowed will disqualify you from payment.</b>
    </p>
<?php else: ?>
    <p>
        Your study condition could not be determined. Please contact the study administrator.
    </p>
<?php endif; ?>

<p>Please wait while we start your editor, this will only take a couple of seconds. You can start as soon as the button shows <b>Start Study</b>.</p>
        </div>
        <div class="col-lg-6">
            <img src="static/img/example_interface.png" style="width:100%;border:1px solid black" alt="Screenshot of study interface" />
            <p>Interface screenshot</p>
        </div>
    </div>
    <button class="btn btn-lg btn-warning" id="loadingButton">
        <span class="glyphicon glyphicon-refresh spinning"></span> Preparing your notebook...    
    </button>
    <hr class="featurette-divider">

    <script>
    function executeQuery() {
      $.post("getAssignedInstance.php",
        {
            userid: "<?php echo $uniqid; ?>",
            token2: "<?php echo $token2; ?>"
        },
        function(data, status){
            if(data != 'error'){
                if(data.length > 5){
                    $('#loadingButton').html("Start study");
                    $('#loadingButton').removeClass("btn-warning");
                    $('#loadingButton').addClass("btn-success");
                    $('#loadingButton').click(function() {
                       window.location = data;
                    });
                    //window.location = data;
                } else {
                    setTimeout(executeQuery, 5000);
                }
            } else {
                    $('#loadingButton').html("An error occured, please try again later.");
                    $('#loadingButton').removeClass("btn-warning");
                    $('#loadingButton').addClass("btn-danger");
            }
        });
    }

    // run the first time; all subsequent calls will take care of themselves
    setTimeout(executeQuery, 1000);
    </script>


<?php include('template/bodyend.html') ?>

</html>
