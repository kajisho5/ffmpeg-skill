<h1>FAQ</h1>
<p class="lede">What ffmpeg-skill does on this machine, from the scripts.</p>
<nav class="toc" aria-label="Topics">
  <ul>
    <li><a href="#safety">Safety and files</a></li>
    <li><a href="#editing">Editing behaviour</a></li>
    <li><a href="#verification">Verification and failures</a></li>
    <li><a href="#audio">Audio and captions</a></li>
    <li><a href="#scale">Scale and tooling</a></li>
  </ul>
</nav>
<div id="faq-list">

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
</section>
</div>
