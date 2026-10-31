<?php /* Static, participant-facing NERDs fuzzing guide. No session state or secrets. */ ?>
<section class="nerds-howto-content" aria-labelledby="nerds-howto-heading">
<h2 id="nerds-howto-heading">NERDs Fuzzing Guide</h2>
<p>Use this guide to learn the mechanics of coverage-guided fuzzing in the NERDs CLI. The steps explain how to operate the tools, not how to solve the assigned investigation.</p>
<h3>Before you begin</h3>
<p>Read the task description first. Work only in the assigned task workspace. A harness is a small program that supplies inputs to the target; a corpus is a saved collection of test inputs.</p>
<ol>
<li><strong>Open the assigned workspace</strong><pre><code>cd ~/fuzz-study/work</code></pre><p>This is your editable workspace. Each task has its own copy of the source files.</p></li>
<li><strong>Explore the project</strong><pre><code>ls</code></pre><p>Look at the Makefile, harnesses/, src/, and include/ before choosing a fuzzing target.</p></li>
<li><strong>Build the available harnesses</strong><pre><code>make CC=/usr/bin/clang-19</code></pre><p>Builds the targets with the installed Clang 19 compiler and its libFuzzer/AddressSanitizer libraries. If the build fails, read the terminal error before making changes.</p></li>
</ol>
<h3>Start fuzzing</h3>
<p>Choose the harness you want to investigate. The commands below use fuzz_a as an example; fuzz_b and fuzz_c may also be available.</p>
<ol>
<li><strong>Create a persistent input corpus</strong><pre><code>mkdir -p ../runs/corpus-a</code></pre><p>Keeping the corpus in ../runs lets you reuse its inputs instead of starting from scratch each time.</p></li>
<li><strong>Run a short campaign</strong><pre><code>./fuzz_a ../runs/corpus-a -max_total_time=120</code></pre><p>Runs libFuzzer for up to two minutes. Watch the output for runs, coverage, newly discovered inputs, and sanitizer errors. The collector records campaign activity.</p></li>
<li><strong>Optional quick check</strong><pre><code>./fuzz_a -runs=100</code></pre><p>Runs at most 100 executions when you want a quick sanity check without a longer timed campaign.</p></li>
</ol>
<h3>Stop and continue</h3>
<p>You may stop a campaign and come back to the same harness. Keep your saved corpus between runs.</p>
<ol>
<li><strong>Stop an active campaign</strong><pre><code>Ctrl+C</code></pre><p>Click the CLI terminal and press Control+C. Wait for the program to return to the shell prompt; do not close or kill the container.</p></li>
<li><strong>Continue using saved inputs</strong><pre><code>./fuzz_a ../runs/corpus-a -max_total_time=120</code></pre><p>Using the same corpus directory starts another campaign seeded with the inputs already collected. The two-minute limit applies to this new run.</p></li>
<li><strong>Try a different harness</strong><pre><code>./fuzz_b ../runs/corpus-b -max_total_time=120</code></pre><p>Create ../runs/corpus-b first with mkdir -p; keep the corpora separate for clarity.</p></li>
</ol>
<h3>Investigate outcomes</h3>
<p>Use the terminal output and source files to decide what to try next; not every campaign will discover a crash.</p>
<ol>
<li><strong>Review saved runs</strong><pre><code>ls ../runs</code></pre><p>Inspect corpora and other files you have saved during this task.</p></li>
<li><strong>Review the current harness source</strong><pre><code>ls harnesses</code></pre><p>You may inspect and modify your task&#x27;s editable files. Rebuild after source changes.</p></li>
<li><strong>If a crash occurs</strong><pre><code>ls crash-*</code></pre><p>The fuzzer may save a crashing input in the current directory; preserve it and the terminal output. If there is no crash file, this command may report no match.</p></li>
</ol>
<h3>Key terms</h3>
<dl>
<dt>Harness</dt><dd>Code that feeds test inputs to the program or function being fuzzed.</dd>
<dt>Corpus</dt><dd>Inputs reused as seeds for future fuzzing runs.</dd>
<dt>Coverage</dt><dd>A measure of the code paths or execution edges exercised by inputs.</dd>
<dt>Crash artifact</dt><dd>An input saved after a failure; keep it for examination and reproduction.</dd>
</dl>
<h3>During the study</h3>
<ul>
<li>Use only the internal CLI and BROWSER tabs for study work. If you need AI or web search, open it inside the NERDs Browser so the study can capture relevant interactions.</li>
<li>Host-to-NERDs clipboard transfer is restricted; type the short commands in the CLI. Copy/paste between applications inside the NERDs desktop may be available.</li>
<li>After each task, choose Finish Task if you believe you have finished, or Skip Task if you want to stop without finishing. Both choices preserve work and advance the study.</li>
<li>If a command fails, keep the output and try to understand the error. You are not required to find a crash.</li>
</ul>
</section>
