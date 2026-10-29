<h1>FAQ</h1>
<p class="lede">What ffmpeg-skill does on this machine, from the scripts.</p>
<nav class="toc" aria-label="Topics">
  <ul>
    <li><a href="#start">Getting started</a></li>
    <li><a href="#compat">Compatibility</a></li>
    <li><a href="#safety">Safety and files</a></li>
    <li><a href="#editing">Editing behaviour</a></li>
    <li><a href="#verification">Verification and failures</a></li>
    <li><a href="#audio">Audio and captions</a></li>
    <li><a href="#scale">Scale and tooling</a></li>
    <li><a href="#compare">Comparison</a></li>
  </ul>
</nav>
<div id="faq-list">

<section class="topic" id="start">
<h2>Getting started</h2>

<article class="qa" id="install">
  <a class="perma" href="#install" aria-label="Link to this question">#</a>
  <details>
    <summary>How do I install it?</summary>
    <div class="a">
      <p><code>npx ffmpeg-skill</code> copies the skill for Claude Code, into <code>~/.claude/skills/ffmpeg-skill</code>. <code>--cursor</code> uses <code>~/.cursor/skills/ffmpeg-skill</code>. <code>--codex</code> uses <code>~/.agents/skills/ffmpeg-skill</code> (and uninstall also removes an older <code>~/.codex/skills</code> copy). <code>--all</code> does those three. <code>--project</code> writes <code>./.claude/skills/ffmpeg-skill</code>. <code>--dir</code> writes under a directory you name. <code>--uninstall</code> removes the selected targets. The copy is <code>SKILL.md</code>, <code>scripts</code>, <code>templates</code>, <code>references</code>, <code>docs</code>, <code>mcp</code> and <code>package.json</code>.</p>
      <p>Claude Code can also install it as a plugin: <code>/plugin install ffmpeg-skill --marketplace kajisho5/ffmpeg-skill</code>. Older Claude Code adds the marketplace first, then <code>claude plugin install ffmpeg-skill@ffmpeg-skill</code>. The plugin name is <code>ffmpeg-skill:ffmpeg-skill</code>.</p>
      <p><code>npx ffmpeg-skill doctor</code> and <code>npx ffmpeg-skill contract --json</code> run <code>scripts/_contract.py</code>. On Windows the installer looks for <code>python3</code>, then <code>python</code>, then <code>py</code>, and keeps the first that is Python 3.9 or newer.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L8-L19">install.js:8</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L30">install.js:30</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L116-L132">install.js:116</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L563-L583">README.md:563</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="no-node">
  <a class="perma" href="#no-node" aria-label="Link to this question">#</a>
  <details>
    <summary>Can I install it without Node?</summary>
    <div class="a">
      <p>Yes. The README says to clone the repository and copy <code>SKILL.md</code>, <code>scripts/</code>, <code>references/</code> and <code>mcp/</code> into the agent’s skills directory. That list is shorter than the npx payload, which also copies <code>templates/</code>, <code>docs/</code> and <code>package.json</code>. <code>render.py --template</code> reads <code>templates/&lt;name&gt;.json</code> beside the scripts, so a copy that omits <code>templates/</code> does not have the shipped templates. Node is only required for the <code>npx</code> installer (Node 16+). The tools themselves are Python.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L585">README.md:585</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L611">README.md:611</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L30">install.js:30</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/render.py#L98">render.py:98</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/render.py#L174-L182">render.py:174</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="updates">
  <a class="perma" href="#updates" aria-label="Link to this question">#</a>
  <details>
    <summary>Does an installed copy update itself?</summary>
    <div class="a">
      <p>No. Re-run <code>npx ffmpeg-skill</code> (or the same flags you installed with) to refresh the copy. The installer writes the new tree beside the old one and swaps it into place, so a killed upgrade leaves the previous install. A Claude Code plugin updates with <code>claude plugin update</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L18-L19">install.js:18</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L180-L196">install.js:180</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L575">README.md:575</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="skill-vs-mcp">
  <a class="perma" href="#skill-vs-mcp" aria-label="Link to this question">#</a>
  <details>
    <summary>What is the difference between the skill and the MCP server?</summary>
    <div class="a">
      <p>The skill is <code>SKILL.md</code> plus the Python scripts an agent runs. The MCP server is <code>mcp/server.py</code>, a stdio JSON-RPC transport with no tool table of its own: <code>tools/list</code> and the argument mapping come from the contract. Any client that speaks MCP over stdio can launch it. The server appends <code>--json</code> except for <code>look</code> and <code>probe</code>. On Windows, if <code>python3</code> is not on PATH, the client’s command should be <code>python</code> (or <code>py</code>).</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/mcp/server.py#L1-L10">server.py:1</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1806-L1810">_contract.py:1806</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L351-L359">README.md:351</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="which-agents">
  <a class="perma" href="#which-agents" aria-label="Link to this question">#</a>
  <details>
    <summary>Which agents can use it?</summary>
    <div class="a">
      <p>The installer has targets for Claude Code, Cursor and Codex. Any agent that can read <code>SKILL.md</code> and run the scripts can use the skill without those directories. Any MCP client that can start a stdio server can use <code>mcp/server.py</code>. The published agent evaluations named in the README are a Sonnet agent with an Opus grader; that is a separate question.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/bin/install.js#L125-L131">install.js:125</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/package.json#L3">package.json:3</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/mcp/server.py#L13-L17">server.py:13</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="license">
  <a class="perma" href="#license" aria-label="Link to this question">#</a>
  <details>
    <summary>What license is it under?</summary>
    <div class="a">
      <p>MIT. Copyright (c) 2026 kajisho5. The same license name is in <code>package.json</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/LICENSE#L1-L3">LICENSE:1</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/package.json#L27">package.json:27</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="compat">
<h2>Compatibility</h2>

<article class="qa" id="versions">
  <a class="perma" href="#versions" aria-label="Link to this question">#</a>
  <details>
    <summary>Which FFmpeg and Python versions does it need, and how does doctor check?</summary>
    <div class="a">
      <p>The tools need FFmpeg 5.0 or later and Python 3.9 or later, standard library only. FFmpeg 6.1+ is recommended: 5.x still works, is deprecated since 2.14.0, and 3.0 requires 6.1. Python 3.10+ is recommended: 3.9 still works, is deprecated since 2.10.9, and 3.0 drops it. <code>doctor</code> and the npx installer print that warning. Node 16+ is only for the installer.</p>
      <p><code>doctor</code> runs <code>ffmpeg -encoders</code>, <code>-filters</code> and <code>-bsfs</code> and marks each capability the contract names <code>available</code>, <code>missing</code> or <code>unknown</code>. Exit 0 when everything required is available, 1 when something required is missing, 2 when nothing required is proven missing but a required capability is unknown. CI on every pull request runs FFmpeg 5.1.1, 6.1, 7.1, 8.x and 9.x, on Python 3.9 and 3.13.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L470">README.md:470</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L609-L611">README.md:609</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1814">_contract.py:1814</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L984-L1002">_contract.py:984</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1936-L1939">_contract.py:1936</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="doctor-usable">
  <a class="perma" href="#doctor-usable" aria-label="Link to this question">#</a>
  <details>
    <summary>Does <code>doctor</code> saying ok mean every tool can run?</summary>
    <div class="a">
      <p>No. <code>ok</code> means nothing required by every tool is missing. <code>doctor --json</code>’s <code>tools</code> field is per tool: <code>usable</code>, <code>missing</code> and <code>fix</code>. A plain Homebrew <code>ffmpeg</code> can be <code>ok</code> while <code>caption</code> is <code>usable: no</code> because <code>subtitles</code> is absent. <code>gpu_encoders</code> lists nvenc, videotoolbox, qsv, vaapi and amf when the build was compiled with them. That list is not a successful encode, and it does not change <code>ok</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L117">README.md:117</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L372-L374">README.md:372</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="windows">
  <a class="perma" href="#windows" aria-label="Link to this question">#</a>
  <details>
    <summary>Does it run on Windows?</summary>
    <div class="a">
      <p>CI runs the tests on Windows with the 9.x gyan.dev FFmpeg build, on Python 3.9 and 3.13. The README’s install line for FFmpeg there is <code>winget install Gyan.FFmpeg</code>. A python.org install exposes <code>python</code> or <code>py</code>, not <code>python3</code>, unless Python came from the Microsoft Store; the installer and MCP docs say to use <code>python</code> in that case.</p>
      <p>The real-device corpus has been run on Linux and macOS. The README says the full corpus has not been run on Windows, and an install by someone other than the maintainer has not been reproduced there. <a href="https://github.com/kajisho5/ffmpeg-skill/issues/143">Issue #143</a> is still open: it tracks real-hands verification of Windows, Cursor and Codex installs on machines that are not the maintainer’s, plus editor reviews.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L470">README.md:470</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L157">README.md:157</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L600">README.md:600</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L490-L492">README.md:490</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/issues/143">issue #143</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="homebrew">
  <a class="perma" href="#homebrew" aria-label="Link to this question">#</a>
  <details>
    <summary>Why does a Homebrew ffmpeg lack subtitles or drawtext?</summary>
    <div class="a">
      <p>The plain Homebrew <code>ffmpeg</code> formula lacks <code>subtitles</code>, <code>drawtext</code> and <code>zscale</code>. <code>ffmpeg-full</code> has them and is keg-only, so installing it does not put it on PATH. If the <code>ffmpeg</code> on PATH is that lean formula, the skill uses <code>ffmpeg-full</code> from the same Homebrew prefix (<code>opt/ffmpeg-full/bin</code>) for both <code>ffmpeg</code> and <code>ffprobe</code>. <code>doctor</code> says so. Any other <code>ffmpeg</code> on PATH is used as it is.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L598">README.md:598</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L602">README.md:602</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="safety">
<h2>Safety and files</h2>

<article class="qa" id="overwrite">
  <a class="perma" href="#overwrite" aria-label="Link to this question">#</a>
  <details>
    <summary>Will it overwrite my files, or can an agent pass <code>-y</code>?</summary>
    <div class="a">
      <p>No tool writes its input. Every contract entry has <code>mutates_input: false</code>, and an output that resolves to the same file as an input is refused before ffmpeg (<code>error.reason: output_is_input</code>). That refusal does not look at <code>--overwrite</code>. The default path is a new file, <code>&lt;stem&gt;_&lt;operation&gt;.&lt;ext&gt;</code> (<code>default_output</code>). A different path that already exists is refused before ffmpeg, including on a dry run (<code>error.reason: output_exists</code>, <code>kind: input</code>), unless <code>--overwrite</code> is passed. The replacement is encoded to a hidden sibling (<code>.{stem}.ffskill-&lt;pid&gt;&lt;ext&gt;</code>) and moved into place only after the encode succeeds, so a failed run leaves the existing file.</p>
      <p><code>ffmpeg_base()</code> appends <code>-y</code> when its <code>overwrite</code> argument is true and <code>-n</code> when it is false. The default is true, and every call site uses that default, so the ffmpeg argv that actually runs carries <code>-y</code>. A caller cannot pass <code>-y</code> through a tool: a raw ffmpeg flag is not an argument any script accepts. The <code>-y</code> on that argv does not replace a file the caller did not consent to replace, because the existing-output refusal runs first, and a consented overwrite is written to the sibling temp rather than opened in place.</p>
      <p>An output argument that starts with <code>-</code> skips the same-file check, the overwrite check, the path check, the output lock and that staging, the same way <code>-</code> and a <code>pipe:</code> output do.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1539">_contract.py:1539</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L556-L579">runner.py:556</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/decision.py#L117-L120">decision.py:117</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L811-L859">runner.py:811</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L879-L902">runner.py:879</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1385-L1388">runner.py:1385</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L492">runner.py:492</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="spaces">
  <a class="perma" href="#spaces" aria-label="Link to this question">#</a>
  <details>
    <summary>Does it handle filenames with spaces?</summary>
    <div class="a">
      <p>Yes. ffmpeg and ffprobe are started with an argument list, not a shell string. <code>run()</code> uses <code>subprocess.Popen</code> on that list, and the contract records <code>execution.shell: false</code> and “argv list only”. <code>shell=True</code> does not appear in <code>scripts/</code> or <code>mcp/server.py</code>; a contract test fails the build if it does. A path with a space is one element of that list. <code>shell_quote()</code> only formats the command line that is printed and stored in <code>commands</code>; it is not how the process is launched.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1263">runner.py:1263</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L470-L471">runner.py:470</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1379-L1382">runner.py:1379</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1816-L1818">_contract.py:1816</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/tests/test_contract.py#L3713-L3719">test_contract.py:3713</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="local">
  <a class="perma" href="#local" aria-label="Link to this question">#</a>
  <details>
    <summary>Is it local, and does it upload media?</summary>
    <div class="a">
      <p>The contract sets <code>execution.network</code> to false and lists network access as not provided. The scripts call ffmpeg and ffprobe on this machine. They do not upload the file.</p>
      <p>Optional speech recognition is the exception the contract names. <code>--transcribe</code>, and <code>silence.py --filler --transcribe</code>, can start a local engine (whisper.cpp, openai-whisper, faster-whisper, parakeet). The media is not uploaded. faster-whisper, parakeet-mlx and openai-whisper may download model weights the first time they run. <code>HF_HUB_OFFLINE=1</code> keeps faster-whisper and parakeet-mlx on a copy already cached. whisper.cpp and parakeet.cpp do not download. If no engine is installed, the tool refuses and names the installs.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1812">_contract.py:1812</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1815-L1832">_contract.py:1815</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="editing">
<h2>Editing behaviour</h2>

<article class="qa" id="raw-ffmpeg">
  <a class="perma" href="#raw-ffmpeg" aria-label="Link to this question">#</a>
  <details>
    <summary>Can I pass raw ffmpeg arguments, or a filter_complex?</summary>
    <div class="a">
      <p>Each operation is a script whose flags are its argparse parser, and that parser is what <code>contract --json</code> and the MCP <code>inputSchema</code> are built from. CI fails the build when those drift from the scripts. A caller-supplied filter graph, <code>-vf</code> string, or other ffmpeg option is not an argument any script accepts. <code>doctor</code> reads <code>ffmpeg -filters</code> (and <code>-encoders</code>, <code>-bsfs</code>) and reports a filter a tool needs before a job runs into it. MCP does accept an <code>argv</code> array, and that array is the named script’s own CLI flags, still bound to that script: the script’s flags, never an ffmpeg command line and never a shell.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L410">README.md:410</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/mcp/server.py#L58-L89">server.py:58</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="filter-graph">
  <a class="perma" href="#filter-graph" aria-label="Link to this question">#</a>
  <details>
    <summary>Does it validate the filter graph before running?</summary>
    <div class="a">
      <p>No. <code>--dry-run</code> prints the ffmpeg command a writing tool would run and does not start ffmpeg, so ffmpeg never parses that filter graph. ffprobe still runs when the tool probes an input that exists. Unless <code>--overwrite</code> is passed, an existing output is refused (<code>kind: input</code>) before ffmpeg. An output that is the same file as an input is refused either way. No media file is written, and <code>verified</code> is false; <code>--plan FILE</code> does write the plan JSON. A path that is not on disk yet is not measured: the probe is a stub (0×0, duration 0), so a number taken from it is not a measurement. The measuring tools (<code>probe</code>, <code>check</code>, <code>sync</code>, <code>multicam</code>, <code>scenes</code>, <code>cropdetect</code>, <code>report</code>, <code>silence</code>, <code>loudness</code>, <code>stabilize</code>) still run their measurements; only the artifact is skipped, and <code>silence</code> with <code>--filler --transcribe</code> also runs the speech engine, which may download a model. <code>overlay</code> measures the lines of a multi-line <code>--text</code> with one drawtext on a generated frame on FFmpeg 8.0, 8.0.1 and 8.1.0, where it draws them one by one. <code>verify</code> accepts <code>--dry-run</code> and ignores it: its steps run. <code>--plan FILE</code> is that dry run written down — the planned argv, the command lines, and a fingerprint of each existing input (size, plus a sha256 of the first and last 8 MiB). <code>render.py</code> and <code>verify.py</code> refuse <code>--plan</code>. <code>render.py FILE</code> runs a plan only when those fingerprints still match (a mismatch is refused with each input’s expected and actual fingerprint in <code>error.details</code>, and logged to <code>&lt;plan&gt;.audit.jsonl</code>), by running the tool again with the planned argv, not by executing the recorded ffmpeg lines; <code>--dry-run</code> on that run only prints them. <code>doctor</code> reports whether the filters, encoders and bitstream filters the contract names are in this build (<code>ffmpeg -filters</code>, <code>-encoders</code>, <code>-bsfs</code>) and which fonts are installed. A name in that listing is not a check of the graph this command would build, and a listed GPU encoder is not a successful encode.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1051-L1052">runner.py:1051</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L236-L251">_contract.py:236</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/verify.py#L116">verify.py:116</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="cut-keyframes">
  <a class="perma" href="#cut-keyframes" aria-label="Link to this question">#</a>
  <details>
    <summary>What does cut do when a trim would snap to a keyframe?</summary>
    <div class="a">
      <p><code>cut.py</code> tries a lossless stream copy first (<code>-c copy</code>). A video copy starts on a keyframe, so the picture can begin at an earlier keyframe than <code>--start</code>. <code>--tolerance</code> is how many seconds that landing may miss by before the segment is re-encoded. The default is <code>0.5</code>, and a miss of exactly <code>0.5</code> s is re-encoded: the copy is kept only when the miss is strictly under the limit. <code>--tolerance -1</code> keeps the copy for a keyframe snap. A <code>--segments</code> join can still be re-cut at that setting, for open GOPs, a later B-frame <code>.mp4</code>/<code>.mov</code> segment that starts between keyframes, or a join that fails its check. <code>--accurate</code> re-encodes from the start, frame-accurate for video and sample-accurate for audio. A source whose nominal frame rate and average frame rate differ is re-encoded too (<code>--vfr-guard</code>, default <code>average</code>).</p>
      <p>With <code>--json</code>, <code>mode</code> is <code>copy</code> when nothing re-encoded, <code>accurate</code> when <code>--accurate</code> was passed or a guard forced that path, and <code>hybrid</code> when a copy was asked for and a segment or the join re-encoded anyway. <code>keyframe_snapped</code> is true when the whole run stayed a stream copy (<code>precision</code> is <code>packet</code>). Whether a copied start actually moved is <code>start_snapped</code>. <code>duration_error_ms</code> is the probed output duration minus the requested duration, in milliseconds, and is null on <code>--dry-run</code>. <code>reencode_reason</code> lists the causes (<code>tolerance</code>, <code>requested</code>, <code>vfr</code>, <code>vfr_inconclusive</code>, <code>codec</code>, <code>copy_failed</code>, <code>pcm_container</code>, <code>concat_fallback</code>).</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L1314">cut.py:1314</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L554">cut.py:554</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L885">cut.py:885</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L1322-L1324">cut.py:1322</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L1645-L1688">cut.py:1645</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="crop-follow">
  <a class="perma" href="#crop-follow" aria-label="Link to this question">#</a>
  <details>
    <summary>Can a vertical crop follow a person or a product?</summary>
    <div class="a">
      <p>No. Nothing in this repository detects a face, a product or a subject. <code>fit.py --fit crop</code> centres the crop unless you pass <code>--crop-x</code> and <code>--crop-y</code>. Each is a fraction from 0 to 1, default <code>0.5</code>: <code>0</code> is the left or top edge, <code>1</code> is the right or bottom edge. The crop filter is <code>crop=W:H:(in_w-out_w)*crop_x:(in_h-out_h)*crop_y</code>. <code>crop.py</code> cuts the rectangle you pass. <code>cropdetect.py</code> measures letterbox bars, and <code>--motion-centre</code> reports where motion sat each second; it writes no file and picks no crop. <code>sphere.py</code> points a 360 view where you aim it. <code>look.py</code> writes a contact sheet. Choosing what to keep in frame is the caller’s.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/fit.py#L94-L95">fit.py:94</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/fit.py#L111-L114">fit.py:111</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/fit.py#L190">fit.py:190</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="gpu">
  <a class="perma" href="#gpu" aria-label="Link to this question">#</a>
  <details>
    <summary>Does it encode on the GPU?</summary>
    <div class="a">
      <p>The encode path a tool will actually take is Apple VideoToolbox, for h264, hevc and prores, and only on Apple Silicon. <code>--hw</code> asks for it on that call. <code>FFMPEG_SKILL_HW=1</code> makes it the default for every re-encoding tool except <code>export.py</code>’s delivery presets, which take <code>--hw</code> on their own (or <code>render.py --hw</code> for a whole project). AV1 stays on SVT-AV1. nvenc, QSV, VAAPI and AMF are reported by <code>doctor --json</code>’s <code>gpu_encoders</code> when the ffmpeg build was compiled with them, and no tool encodes with them. One build is the exception to opt-in: with no <code>libx264</code> and no <code>libx265</code>, and with <code>h264_videotoolbox</code> or <code>hevc_videotoolbox</code>, those encodes use VideoToolbox without <code>--hw</code> and the result says <code>hw.source</code> is <code>"auto"</code>. <code>--no-hw</code> still asks for the CPU encoder. A VideoToolbox job the hardware refuses is re-encoded on the CPU and the result says so (<code>hw.fallback</code>).</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L430">README.md:430</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="formats">
  <a class="perma" href="#formats" aria-label="Link to this question">#</a>
  <details>
    <summary>Which formats can it read and write?</summary>
    <div class="a">
      <p>Reading is whatever <code>ffprobe</code> and <code>ffmpeg</code> on PATH can open. The skill does not keep a separate list of input containers. For audio outputs, the extension picks the codec: <code>.wav</code> PCM, <code>.flac</code> FLAC, <code>.mp3</code> MP3, <code>.m4a</code> and <code>.aac</code> AAC, <code>.ogg</code> Vorbis, <code>.opus</code> Opus. The README names those same extensions for <code>probe</code>, <code>cut</code>, <code>join</code>, <code>silence</code>, <code>loudness</code>, <code>audio</code>, <code>sync</code> and <code>check --platform podcast</code>.</p>
      <p><code>export.py</code> presets are <code>youtube</code>, <code>youtube4k</code>, <code>reels</code>, <code>tiktok</code>, <code>shorts</code>, <code>linkedin</code>, <code>facebook</code>, <code>x</code>, <code>youtube-hdr</code>, <code>youtube-av1</code>, <code>prores</code>, <code>h265</code>, <code>gif</code> and <code>copy</code>. <code>copy</code> stream-copies the source codecs. ProRes is written as <code>.mov</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/decision.py#L679-L687">decision.py:679</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L284">README.md:284</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/export.py#L6-L21">export.py:6</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="times">
  <a class="perma" href="#times" aria-label="Link to this question">#</a>
  <details>
    <summary>How do I write a time?</summary>
    <div class="a">
      <p>Timestamp flags take seconds, <code>mm:ss</code>, <code>hh:mm:ss</code> with an optional fraction, or SMPTE <code>hh:mm:ss:ff</code> with an optional <code>@fps</code>. Length flags such as <code>--min-silence</code> and <code>--fade</code> are plain seconds. One parser, <code>time_arg</code>, is what the tools call.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/SKILL.md#L61">SKILL.md:61</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L206">README.md:206</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="fast">
  <a class="perma" href="#fast" aria-label="Link to this question">#</a>
  <details>
    <summary>What does <code>--fast</code> do?</summary>
    <div class="a">
      <p><code>--fast</code> is preview quality. When the tool’s <code>--preset</code> is an x264 preset name, it is set to <code>veryfast</code>. It does not change the timeout. On the one-hour measurement, <code>export.py --preset youtube --fast</code> on a 10-minute segment took 162 s, against 514 s without it.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L293">runner.py:293</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L348-L358">runner.py:348</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L552">README.md:552</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="silence-threshold">
  <a class="perma" href="#silence-threshold" aria-label="Link to this question">#</a>
  <details>
    <summary>Why did silence removal find nothing?</summary>
    <div class="a">
      <p>The default threshold is <code>-35</code> dBFS (<code>--threshold</code>). The help text says to use <code>-40</code> to <code>-45</code> for a quiet room. Raise the threshold (for example <code>--threshold -25</code>) or shorten <code>--min-silence</code> when the track is louder than the default and nothing is marked.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/silence.py#L256">silence.py:256</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L397">README.md:397</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="hdr">
  <a class="perma" href="#hdr" aria-label="Link to this question">#</a>
  <details>
    <summary>Does it flatten HDR?</summary>
    <div class="a">
      <p>No. When the probe reports HDR (HDR10, HLG, Dolby Vision, BT.2020), the tools keep it. Convert on purpose with <code>color.py --to-sdr</code> before an H.264 deliverable or a LUT. <code>export.py</code> platform presets are SDR and warn on HDR input. <code>youtube-hdr</code> is the preset that keeps HDR10/HLG tags and refuses an SDR source.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L384">README.md:384</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/export.py#L14">export.py:14</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="join-reencode">
  <a class="perma" href="#join-reencode" aria-label="Link to this question">#</a>
  <details>
    <summary>Does join stream-copy?</summary>
    <div class="a">
      <p>No. <code>join.py</code> builds one filter graph (scale, fps, format, and either <code>concat</code> or <code>xfade</code>/<code>acrossfade</code>) and encodes. The one-hour measurement notes that join always re-encodes so it can crossfade and conform. A clip with no audio stream is padded with <code>anullsrc</code>, which is the same gap described under <code>verified: true</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/join.py#L513-L558">join.py:513</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L550">README.md:550</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="verification">
<h2>Verification and failures</h2>

<article class="qa" id="verified">
  <a class="perma" href="#verified" aria-label="Link to this question">#</a>
  <details>
    <summary>Does <code>verified: true</code> mean the output is good?</summary>
    <div class="a">
      <p><code>verified</code> is true when a file was written and every step in <code>verification</code> passed (<code>emit()</code>). For a media file the first step is <code>probe</code>: the file exists, is not empty, and ffprobe reads at least one video or audio stream (<code>verify_output</code>). On <code>--dry-run</code>, <code>verified</code> is false. A tool that measures more adds steps. <code>loudness.py</code> re-measures the file it wrote, <code>export.py</code> compares the platform spec, and <code>render.py</code>’s <code>verified</code> is every stage’s. A miss the tool leaves in the file, such as export loudness outside the platform spec, stays <code>status: completed</code> with <code>verified: false</code>.</p>
      <p>The probe step does not compare the output’s streams with the input’s. <a href="https://github.com/kajisho5/ffmpeg-skill/issues/367">Issue #367</a> is open. It reports that <code>cut.py</code> on some MPEG-TS inputs can drop the whole video stream and still return <code>status: completed</code> and <code>verified: true</code>, including with <code>--accurate</code>; the loss shows up as <code>probe.video</code> null. The follow-up on that issue reports the same class of miss in <code>join.py</code>: a clip with no audio stream is padded with synthesized silence and can still return <code>verified: true</code>. The code does that pad with <code>anullsrc</code> and adds no note for it; the join’s own <code>verification</code> step is duration. A clip that has an audio stream and is silent is a separate case: <code>--on-silent</code> defaults to <code>warn</code>, and that flag’s help says a clip with no audio stream is never counted as silent.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/emit.py#L389-L400">emit.py:389</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/probe.py#L122-L135">probe.py:122</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/docs/design-decisions.md#L381-L386">design-decisions.md:381</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/join.py#L473-L479">join.py:473</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/join.py#L565-L572">join.py:565</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/issues/367">issue #367</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="failure">
  <a class="perma" href="#failure" aria-label="Link to this question">#</a>
  <details>
    <summary>What does the agent get back on failure, or during a long job?</summary>
    <div class="a">
      <p>With <code>--json</code>, a failure is one document on stdout: <code>status: failed</code>, <code>exit_code</code>, <code>error.kind</code>, <code>error.message</code>, <code>error.code</code>, <code>error.retryable</code> (always <code>false</code>) and <code>commands</code>. The same message goes to stderr as <code>error: …</code>. When ffmpeg fails inside <code>run()</code>, <code>_fail()</code> sets <code>kind</code> to <code>ffmpeg</code> and <code>code</code> to <code>FFMPEG_EXECUTION_FAILED</code>, puts the last 15 stderr lines in <code>message</code>, and sets <code>ffmpeg_returncode</code> to ffmpeg’s own exit code. The process still exits 1. A tool that reports the failure itself can put stderr in <code>message</code> and leave <code>ffmpeg_returncode</code> unset (<code>cut.py</code> when the re-encode fails; <code>loudness.py</code> when the measurement fails).</p>
      <p>Exit codes: <code>0</code> success, <code>1</code> failure, <code>124</code> timeout, <code>127</code> when ffmpeg or ffprobe is missing, and <code>128</code> plus the signal number when interrupted (<code>130</code> for SIGINT, <code>143</code> for SIGTERM). <code>doctor</code> returns <code>2</code> when a required capability is unknown and nothing required is proven missing.</p>
      <p>The default limit is 1800 seconds per ffmpeg call (<code>DEFAULT_TIMEOUT</code>). <code>--timeout SECONDS</code> or <code>FFMPEG_SKILL_TIMEOUT</code> changes it, and <code>0</code> means no limit. A non-numeric <code>FFMPEG_SKILL_TIMEOUT</code> stays at 1800 and is recorded as <code>timeout_env_invalid</code>; a negative value is read as <code>0</code>. On timeout the process is killed, the partial file is removed, and the document is <code>kind: timeout</code>, exit <code>124</code>. ffprobe and the other non-ffmpeg commands <code>run()</code> starts are capped at 120 seconds (<code>PROBE_TIMEOUT</code>) while a limit is set; <code>--timeout 0</code> removes that cap too. The JSON document is printed when the call finishes. <code>--progress</code> prints percent and ETA on that process’s stderr while ffmpeg encodes. The MCP server waits for the script (<code>run_tool</code>): its outer ceiling is four times the per-call limit plus 60 seconds, and that ceiling is off when the per-call limit is <code>0</code>. A failed call comes back as <code>isError: true</code>, with the child’s document in <code>structuredContent</code> when stdout is JSON, and the last 12 stderr lines in the text. Those progress lines are not sent while the call is still running.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/emit.py#L43-L60">emit.py:43</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L515-L544">runner.py:515</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L67">runner.py:67</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L77-L93">runner.py:77</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1252-L1257">runner.py:1252</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1177-L1184">runner.py:1177</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/mcp/server.py#L161-L169">server.py:161</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1936-L1939">_contract.py:1936</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="structured">
  <a class="perma" href="#structured" aria-label="Link to this question">#</a>
  <details>
    <summary>Are results structured, or only pass or fail?</summary>
    <div class="a">
      <p><code>--json</code> prints one document, and <code>--json-brief</code> is that document trimmed. A success carries <code>status: completed</code>, <code>output</code>, <code>dry_run</code>, <code>commands</code>, <code>verified</code>, <code>verification</code> and, when a media file was written, <code>probe</code> of that file (duration, video, audio, and the rest of the probe object). Fields the tool measured sit beside those, such as <code>cut.py</code>’s <code>mode</code> and <code>duration_error_ms</code>, and <code>loudness.py</code>’s <code>measured</code>, <code>targets</code> and <code>result</code>. <code>diagnostics</code> is included when the run recorded a warning, a fallback or a skip; each entry is <code>{code, message, …}</code>. <code>--json-brief</code> keeps <code>verified</code>, replaces <code>probe</code> with <code>summary</code>, replaces <code>commands</code> with a count, and drops <code>verification</code>. <code>probe.py</code> prints its measurement as JSON without <code>--json</code>. The MCP server appends <code>--json</code> for every tool except <code>look</code> and <code>probe</code> (<code>MCP_JSON_EXEMPT</code>) and returns the document as <code>structuredContent</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/emit.py#L386-L410">emit.py:386</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/emit.py#L111-L124">emit.py:111</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/emit.py#L451-L468">emit.py:451</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/probe.py#L24">probe.py:24</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1600">_contract.py:1600</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/mcp/server.py#L88-L89">server.py:88</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="audio">
<h2>Audio and captions</h2>

<article class="qa" id="loudness">
  <a class="perma" href="#loudness" aria-label="Link to this question">#</a>
  <details>
    <summary>Can it normalise loudness?</summary>
    <div class="a">
      <p><code>loudness.py</code> is a two-pass EBU R128 <code>loudnorm</code>. Pass 1 measures integrated loudness, true peak, LRA and threshold. Pass 2 applies <code>loudnorm</code> in linear mode (<code>linear=true</code>) with those measurements. The defaults are <code>-14</code> LUFS (<code>-I</code> / <code>--lufs</code>, default <code>-14.0</code>), <code>-1</code> dBTP (<code>--tp</code>, default <code>-1.0</code>) and <code>11</code> LU (<code>--lra</code>, default <code>11.0</code>). After the file is written, the same measurement runs on the output. If the encoded true peak is more than <code>0.1</code> dB over <code>--tp</code>, it re-encodes and measures again, up to five further encodes, and the result reports <code>tp_ceiling_used</code> and <code>encodes</code>. On a video file the picture is stream-copied (<code>-c:v copy</code>) and the audio is AAC at <code>192k</code> unless <code>--audio-bitrate</code> is set; when that bitrate was not passed, the retries go to <code>256k</code>, then <code>320k</code>, then a lower loudnorm ceiling. A passed <code>--audio-bitrate</code> skips the <code>256k</code>/<code>320k</code> steps. The <code>verification</code> step <code>loudness</code> is ok when the file is silent, or when integrated loudness is within <code>1.0</code> LU of the target and true peak is at most <code>0.1</code> dB over <code>--tp</code>. More than <code>1.0</code> LU off the target keeps the file, sets that step’s <code>ok</code> to false (so <code>verified</code> is false) and explains it in <code>result.note</code>. True peak still over the ceiling after those encodes fails with <code>kind: verification</code>. <code>--measure-only</code> prints the measurement and writes no file.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/loudness.py#L1-L5">loudness.py:1</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/loudness.py#L50-L52">loudness.py:50</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/loudness.py#L85-L110">loudness.py:85</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/loudness.py#L120-L165">loudness.py:120</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="second-audio">
  <a class="perma" href="#second-audio" aria-label="Link to this question">#</a>
  <details>
    <summary>Does it keep a second audio track?</summary>
    <div class="a">
      <p><code>probe.py</code> lists every audio stream under <code>audio_streams</code>. Most writing tools then keep one of them.</p>
      <p>These map a single stream, <code>--audio-stream</code> default <code>0</code> (the first track in file order): <code>fit.py</code>, <code>caption.py</code> (burn and mux), <code>graphics.py</code>, <code>overlay.py</code>, <code>color.py</code> on a re-encode, <code>deinterlace.py</code>, <code>denoise.py</code>, <code>redact.py</code>, <code>sphere.py</code>, <code>straighten.py</code> and <code>waveform.py</code>. The map is <code>-map 0:a:N</code>. A second track is not in the output. <code>audio.py</code> processes one stream the same way (<code>--audio-stream</code>, default <code>0</code>) and maps that result plus <code>0:v:0</code> when the output is a video. <code>loudness.py</code> on a video file maps <code>-map 0:v:0 -map 0:a:0</code>. <code>join.py</code> uses each clip’s <code>a:0</code> only (a clip with no audio stream is padded with <code>anullsrc</code> instead). A <code>cut.py --segments</code> re-encode maps <code>[i:a:0]</code>.</p>
      <p><code>cut.py</code>’s single-segment stream copy passes <code>-c copy</code> and does not pass <code>-map 0</code>. Its re-encode adds <code>-sn -dn</code> and does not map every audio stream. <code>color.py</code>’s stream-copy retag is the path that does pass <code>-map 0 -c copy</code>, which that file’s comment describes as keeping every stream, extra audio included. <code>metadata.py</code> also passes <code>-map 0</code> and <code>-c copy</code>. <code>export.py</code> sets one <code>-c:a</code> line (or <code>-an</code>) and does not pass <code>-map 0</code> or a map per audio stream.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/probe.py#L304-L305">probe.py:304</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/fit.py#L72-L75">fit.py:72</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/fit.py#L219-L221">fit.py:219</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/caption.py#L1386">caption.py:1386</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/loudness.py#L107">loudness.py:107</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/join.py#L473-L479">join.py:473</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L108-L115">cut.py:108</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/cut.py#L1090">cut.py:1090</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/color.py#L289">color.py:289</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/metadata.py#L242-L249">metadata.py:242</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/export.py#L246">export.py:246</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="captions">
  <a class="perma" href="#captions" aria-label="Link to this question">#</a>
  <details>
    <summary>Can it burn captions in, or remove burned-in captions?</summary>
    <div class="a">
      <p><code>caption.py</code> burns captions into the picture by default (<code>--mode burn</code>, the <code>subtitles</code> or <code>ass</code> filter). <code>--karaoke</code> highlights word by word. <code>--karaoke-style</code> is <code>sweep</code> (the default: a colour fill, one Dialogue event per cue) or <code>word</code> (one Dialogue event per word, the active word scaled by <code>--karaoke-scale</code>, default <code>112</code>, and emboldened). <code>--mode mux</code> copies the video and one audio stream and adds the SRT as a soft subtitle track instead of burning it. The cue text is burned as given; the tool does not rewrite it.</p>
      <p>Nothing removes burned-in captions. The closest tool is <code>redact.py --mode delogo</code>, which fills a rectangle you already know, sitting still for the whole clip, from the picture around it. That is a 1 px border blend. It is not inpainting: a logo that moves, or burned-in subtitles whose position changes, is out of scope. The same known box can be obscured instead, with <code>--mode blur</code> or <code>--mode pixelate</code>. None of the three finds the box. <code>delogo</code> also needs the box at least 1 px inside the frame, and it only interpolates 8-bit YUV, so an HDR or 10-bit source is refused until <code>color.py --to-sdr</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/caption.py#L912-L914">caption.py:912</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/caption.py#L1005-L1015">caption.py:1005</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/caption.py#L1361-L1386">caption.py:1361</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/caption.py#L1636">caption.py:1636</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/redact.py#L1-L17">redact.py:1</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="caption-text">
  <a class="perma" href="#caption-text" aria-label="Link to this question">#</a>
  <details>
    <summary>Will it rewrite my caption text to make it fit?</summary>
    <div class="a">
      <p>No. <code>caption.py</code> burns the cues as given. Line breaks, timing and type size can change. <code>--fit-size</code> walks the size down until the cue fits. A split cue, a dropped cue, transcription, or <code>--emoji none</code> (which removes glyphs from the drawn text) are reported as not unchanged. The result key <code>text_unchanged</code> is true only when none of those happened.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/caption.py#L1643-L1657">caption.py:1643</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/SKILL.md#L50">SKILL.md:50</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="scale">
<h2>Scale and tooling</h2>

<article class="qa" id="tool-count">
  <a class="perma" href="#tool-count" aria-label="Link to this question">#</a>
  <details>
    <summary>Are 42 tools too many for an agent?</summary>
    <div class="a">
      <p><code>tools/list</code> advertises a core set of 12. The set is <code>MCP_CORE_TOOLS</code>: <code>render</code>, <code>look</code>, <code>caption</code>, <code>export</code>, <code>check</code>, <code>fit</code>, <code>cut</code>, <code>audio</code>, <code>loudness</code>, <code>graphics</code>, <code>silence</code>, <code>probe</code>. <code>tools/list</code> yields the members the contract contains, in contract order, which is alphabetical: <code>audio</code>, <code>caption</code>, <code>check</code>, <code>cut</code>, <code>export</code>, <code>fit</code>, <code>graphics</code>, <code>look</code>, <code>loudness</code>, <code>probe</code>, <code>render</code>, <code>silence</code>. The comment on <code>MCP_CORE_TOOLS</code> records the selection: the tools eval iterations 17–20 named most often in the ground-truth <code>expect</code> lists, across the 118 prompts in <code>evals/agent_prompts*.json</code> (render, look, caption, export and check at least 10 hits each; fit, cut, audio, loudness, graphics, silence and probe at least 6). The other 30 stay callable by name through <code>tools/call</code> either way, and <code>contract --json</code> still describes all 42. <code>FFMPEG_SKILL_MCP_FULL</code> unset, empty, or <code>0</code> keeps the core set; any other value (the usual one is <code>1</code>) makes <code>tools/list</code> return all 42. Which script a request should call is the “Request → script” table in <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/SKILL.md#L57">SKILL.md</a>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1606-L1613">_contract.py:1606</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L747-L748">_contract.py:747</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/mcp/server.py#L179-L191">server.py:179</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/SKILL.md#L57">SKILL.md:57</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="long-files">
  <a class="perma" href="#long-files" aria-label="Link to this question">#</a>
  <details>
    <summary>What about a long file, and what does <code>--dry-run</code> do?</summary>
    <div class="a">
      <p>The default limit is 1800 seconds per ffmpeg call (<code>DEFAULT_TIMEOUT</code>). <code>--timeout SECONDS</code> or <code>FFMPEG_SKILL_TIMEOUT</code> changes it, and <code>0</code> means no limit. A timeout kills that ffmpeg, removes the partial file, and returns <code>kind: timeout</code>, exit <code>124</code>. Measured times for a one-hour 1080p file, including a whole-hour export that hit this default, are in <a href="../README.md#a-one-hour-recording">A one-hour recording</a>.</p>
      <p><code>--dry-run</code> on a writing tool prints the ffmpeg command and does not start ffmpeg (<code>run()</code> returns before the process). No media file is written, an existing output is still refused unless <code>--overwrite</code> is passed, and <code>verified</code> is false. <code>DRY_RUN_ANALYSIS</code> names the tools that still measure under <code>--dry-run</code> and write no artifact: <code>sync</code>, <code>multicam</code>, <code>scenes</code>, <code>report</code>, <code>cropdetect</code>, <code>silence</code>, <code>loudness</code>, <code>check</code>, <code>stabilize</code>, <code>overlay</code>. <code>overlay</code>’s measurement runs only for a multi-line <code>--text</code> on FFmpeg 8.0, 8.0.1 and 8.1.0. <code>silence --filler --transcribe</code> also runs the speech engine. <code>probe</code> is read-only, so ffprobe still runs. <code>verify</code> accepts <code>--dry-run</code> and does not forward it (each step’s argv is built without that flag), so its steps run. <code>--plan</code> is covered in the filter-graph answer.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L67">runner.py:67</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L872-L876">runner.py:872</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_common/runner.py#L1051-L1052">runner.py:1051</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L236-L251">_contract.py:236</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/verify.py#L116">verify.py:116</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="batch">
  <a class="perma" href="#batch" aria-label="Link to this question">#</a>
  <details>
    <summary>How does batch processing and its cache work?</summary>
    <div class="a">
      <p><code>batch.py</code> applies one recipe to each file in a folder. The cache file is <code>.ffskill_cache.json</code> in the output directory. <code>--force</code> ignores it. <code>--jobs N</code> runs N files at once, or <code>auto</code> for <code>min(cpu_count, 4)</code>, and the cap is <code>min(N, cpu_count, 8)</code>.</p>
      <p>A file’s cache identity is a sha1 of its name, size, mtime in whole seconds, and the first and last 1 MiB (the last megabyte is read only when the file is larger than 2 MiB). The recipe is hashed too, including the text of a <code>project</code> file it names. The GPU flag is part of the key, so a <code>--hw</code> output is not served to a CPU run. A change that leaves the name, size, that mtime-second, and those two megabytes the same does not change the file key.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/batch.py#L50-L59">batch.py:50</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/batch.py#L62-L78">batch.py:62</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/batch.py#L81-L86">batch.py:81</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/batch.py#L312-L316">batch.py:312</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/batch.py#L368">batch.py:368</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="render-cache">
  <a class="perma" href="#render-cache" aria-label="Link to this question">#</a>
  <details>
    <summary>How does <code>render.py --cache</code> decide a stage is the same?</summary>
    <div class="a">
      <p><code>--cache DIR</code> is opt-in. There is no default directory. The key is a sha1 of the stage name, tool, arguments (files that exist are replaced by the same fingerprint <code>batch.py</code> uses), input fingerprints, the forwarded child flags except <code>--dry-run</code>, codec, output extension, the hardware environment, the ffmpeg build banner, the skill version and the contract version. A different ffmpeg build or skill version does not reuse an entry. If the banner cannot be read, the key falls back to the major.minor pair and says so.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/render.py#L658-L665">render.py:658</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/render.py#L697-L726">render.py:697</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/render.py#L1057-L1060">render.py:1057</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="prompts">
  <a class="perma" href="#prompts" aria-label="Link to this question">#</a>
  <details>
    <summary>What are the MCP prompts?</summary>
    <div class="a">
      <p>The server advertises five prompts: <code>reel</code>, <code>podcast</code>, <code>multicam</code>, <code>delivery_check</code> and <code>hdr</code>. <code>prompts/get</code> returns text that names commands the tools already run. They are not extra tools.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/scripts/_contract.py#L1626-L1628">_contract.py:1626</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L363">README.md:363</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="evals">
  <a class="perma" href="#evals" aria-label="Link to this question">#</a>
  <details>
    <summary>Which models has it been evaluated on?</summary>
    <div class="a">
      <p>The published agent runs in the README are a Sonnet agent. Where an independent grader is named, it is Opus, and the trigger judge is Sonnet. <code>docs/design-decisions.md</code> records that as Claude-only: a number for another vendor was not measured here. <code>evals/run.py</code> is a regex grader that another harness can run on a transcript. The README table is the record of those runs, including the ones that did not score full marks.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/docs/design-decisions.md#L532-L539">design-decisions.md:532</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L504">README.md:504</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="bugs">
  <a class="perma" href="#bugs" aria-label="Link to this question">#</a>
  <details>
    <summary>How do I report a bug?</summary>
    <div class="a">
      <p>Read <code>docs/design-decisions.md</code> first. It lists behaviours that look like bugs and names the test that pins each one. If the report is about one of those, say which sentence no longer holds. A bug report should include the command, the actual and expected behaviour, and <code>python3 scripts/_contract.py doctor --json</code> when the failure might be a missing encoder or filter.</p>
      <p>A security issue goes to GitHub’s private advisory flow (Security tab, Report a vulnerability), not a public issue. <code>SECURITY.md</code> asks for the file, the version, a minimal reproduction and the impact. Only the latest published version is supported.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/CONTRIBUTING.md#L102-L110">CONTRIBUTING.md:102</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/docs/design-decisions.md#L1-L7">design-decisions.md:1</a>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/SECURITY.md#L3-L22">SECURITY.md:3</a>
      </p>
    </div>
  </details>
</article>
</section>

<section class="topic" id="compare">
<h2>Comparison</h2>

<article class="qa" id="remotion">
  <a class="perma" href="#remotion" aria-label="Link to this question">#</a>
  <details>
    <summary>How does ffmpeg-skill compare with Remotion?</summary>
    <div class="a">
      <p>ffmpeg-skill edits footage you already have, on this machine, with FFmpeg tools whose flags are a machine-readable contract (<code>contract --json</code>). Remotion renders a video from React components. They complement each other: this repository does not call Remotion, and a file Remotion writes is an ordinary input (<code>probe.py</code>, <code>cut.py</code>, <code>fit.py</code>, <code>export.py</code>, <code>check.py</code>). <a href="https://github.com/kajisho5/remotion-ffmpeg-skill">remotion-ffmpeg-skill</a> joins the two. It measures the footage with this repo, draws the graphics in Remotion from those measurements, and checks and delivers the result with this repo again. Install both (<code>npx ffmpeg-skill</code>, then <code>npx remotion-ffmpeg-skill</code>). As with the other skills, the dependency runs one way: it calls these tools, and nothing here calls it. HyperFrames renders a video from HTML and is the same kind of neighbour: a file it writes is an ordinary input too.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L414">README.md:414</a>
      </p>
    </div>
  </details>
</article>

<article class="qa" id="other-skills">
  <a class="perma" href="#other-skills" aria-label="Link to this question">#</a>
  <details>
    <summary>Does this repository call the other skills?</summary>
    <div class="a">
      <p>No. The README’s ecosystem list (media analysis, transcription, subtitles, thumbnails, colour grading, motion graphics, QC) reads this repo’s <code>contract --json</code>, tool JSON and <code>doctor</code>. This repository does not call them. The same one-way line is what the Remotion answer says about <code>remotion-ffmpeg-skill</code>.</p>
      <p class="src"><span>Sources</span>
        <a href="https://github.com/kajisho5/ffmpeg-skill/blob/main/README.md#L64-L77">README.md:64</a>
      </p>
    </div>
  </details>
</article>
</section>
</div>
