"""Frame-indexed inclusive-speech edits and source-bound verification for lossless masters."""
import bisect
from contextlib import ExitStack
import hashlib
import json
import math
import os
import sys
import tempfile
from array import array
from pathlib import Path

from _common import STATE, die, guard_sidecar, print_json
from _common.pacing import decoded_pcm, envelope, extract, number, pauses, read_profile
from _common.runner import register_plan_input, run, run_analysis
from _common.emit import write_plan


def frames(path):
    args = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries",
            "frame=best_effort_timestamp_time,duration_time,pkt_duration_time:stream=duration:stream_tags=DURATION", "-of", "json", path]
    document = json.loads(run_analysis(args).stdout)
    data = document["frames"]
    if not data:
        raise ValueError("pacing edits require a video stream")
    pts = [float(f["best_effort_timestamp_time"])*1000 for f in data]
    origin = pts[0]
    if any(a >= b for a, b in zip(pts, pts[1:])):
        raise ValueError("expected increasing video presentation timestamps")
    last = data[-1]
    length = last.get("duration_time") or last.get("pkt_duration_time")
    if not length or float(length) <= 0:
        # Matroska can omit packet durations but record the independently muxed
        # end of this particular track (the container duration may be the audio).
        streams = document.get("streams") or []
        end = streams[0].get("tags", {}).get("DURATION") if streams else None
        if not end and streams and streams[0].get("duration"):
            end = "0:0:" + str(float(streams[0]["duration"]) + origin/1000)
        if not end:
            raise ValueError("final frame duration unavailable")
        h, m, sec = end.split(":")
        track_end = (int(h)*3600 + int(m)*60 + float(sec))*1000
        if track_end <= pts[-1]:
            raise ValueError("final video frame has no positive duration")
        return [t-origin for t in pts+[track_end]]
    return [t-origin for t in pts + [pts[-1] + float(length)*1000]]


def sound(path, stack):
    args = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path]
    streams = json.loads(run_analysis(args).stdout)["streams"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    video = [s for s in streams if s["codec_type"] == "video"]
    if len(audio) != 1 or len(video) != 1 or len(streams) != 2:
        raise ValueError("master requires one aligned audio stream and one video stream")

    # A timestamp discontinuity inside either track is invisible to an end-to-end length check.
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_frames", "-show_entries",
           "frame=best_effort_timestamp_time,nb_samples", "-of", "json", path]
    blocks = json.loads(run_analysis(cmd).stdout)["frames"]
    rate = int(audio[0]["sample_rate"])
    origin = float(blocks[0]["best_effort_timestamp_time"])
    delta = round((origin-float(video[0]["start_time"]))*rate)
    alignment = f"atrim=start_sample={-delta}" if delta < 0 else f"adelay={delta}S:all=1" if delta else ""
    pcm = stack.enter_context(decoded_pcm(path, ["-af", alignment] if alignment else [], "s32le", "i"))
    position = 0
    for block in blocks:
        if abs(float(block["best_effort_timestamp_time"])-origin-position/rate) > .00101:
            raise ValueError("audio timestamps differ from the decoded sample clock")
        position += int(block["nb_samples"])
    return int(audio[0]["sample_rate"]), audio[0]["channels"], pcm, alignment


def ranges(path, end):
    result = json.loads(Path(path).read_text(encoding="utf-8")) if path else []
    if not isinstance(result, list):
        raise ValueError("protect-ranges must be a list")
    for row in result:
        if not isinstance(row, dict) or not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("protected interval requires a reason")
        a, b = row.get("start_ms"), row.get("end_ms")
        if not number(a) or not number(b) or not 0 <= a < b <= end:
            raise ValueError("invalid protected interval in source milliseconds")
    return sorted(result, key=lambda row: row["start_ms"])


def subtract(a, b, protected):
    cursor = a
    pieces = []
    for left, right in protected:
        if left >= b:
            break
        if cursor < left:
            pieces.append((cursor, min(b, left)))
        cursor = max(cursor, right)
    if cursor < b:
        pieces.append((cursor, b))
    return pieces


def splice_shift(pcm, channels, end, start, radius):
    """A common sample shift preserves the sound clock on both sides of the seam."""
    def score(shift):
        pairs = [(pcm[(end-1+shift)*channels+c], pcm[(start+shift)*channels+c]) for c in range(channels)]
        crossings = sum(a*b <= 0 for a,b in pairs)
        return (max(abs(a-b) for a,b in pairs), -crossings,
                max(max(abs(a), abs(b)) for a,b in pairs), abs(shift))
    return min(range(-radius, radius+1), key=score)


def make_plan(path, profile, protect, stack):
    pts = frames(path)
    rate, channels, pcm, alignment = sound(path, stack)
    sample = lambda ms: round(ms * rate / 1000)
    if len(pcm)//channels < sample(pts[-1])-round(rate*.001) or abs(len(pcm)/channels-sample(pts[-1])) > rate*.05:
        raise ValueError("source audio and picture durations differ")
    detection, timing, rules, seam = (profile[k] for k in ("silence_detection", "pacing", "cut_rules", "audio_seam"))
    levels, duration = envelope(path, detection["analysis_bandpass_hz"], alignment)
    spans = pauses(levels, duration, detection)
    protections = ranges(protect, pts[-1])
    margin = max(seam["micro_fade_ms"], seam["zero_cross_search_ms"]) + 1
    reserved = [(p["start_ms"]-margin, p["end_ms"]+margin) for p in protections]
    removed = []
    flags = []
    for a, b in spans:
        if b-a > timing["flag_long_pause_above_ms"]:
            flags.append(dict(start_ms=a, end_ms=b))
        head, tail = a == 0, b == duration
        if head and tail:
            raise ValueError("no detected speech; refusing a whole-program silence edit")
        if head:
            limit = b-timing["trim_leading_max_ms"]
            boundary = pts[min(len(pts)-1, bisect.bisect_left(pts, limit))]
            start, end = 0, min(b, boundary)
        elif tail:
            limit = a+timing["trim_trailing_max_ms"]
            boundary = pts[max(0, bisect.bisect_right(pts, limit)-1)]
            start, end = max(a, boundary), pts[-1]
        elif b-a > timing["max_keep_silence_ms"]:
            total = timing["pad_before_speech_ms"] + timing["pad_after_speech_ms"]
            target = timing["target_keep_silence_ms"]
            post = target * timing["pad_after_speech_ms"] / total if total else target/2
            start, end = a+post, b-(target-post)
            # Frame rounding may spend both pads' headroom when the reference median
            # equals its p95. Widen the deletion only inside this detected pause.
            i = bisect.bisect_left(pts, start)
            j = bisect.bisect_right(pts, end)-1
            if i < len(pts) and j >= 0 and b-a-(pts[j]-pts[i]) > timing["max_keep_silence_ms"]:
                start = max(a, pts[max(0, i-1)])
                end = min(b, pts[min(len(pts)-1, j+1)])
        else:
            continue
        for start, end in subtract(start, end, reserved):
            i = bisect.bisect_left(pts, start)
            j = bisect.bisect_right(pts, end)-1
            prev = removed[-1][1] if removed else 0
            if i > prev and (i-prev < rules["min_clip_frames"] or
                             removed and pts[i]-pts[prev] < rules["merge_gap_below_ms"]):
                continue  # keep the small island of speech and its following pause intact
            if j-i >= rules["min_removed_frames"] and (j == len(pts)-1 or len(pts)-1-j >= rules["min_clip_frames"]):
                removed.append((i, j))
    spans = subtract(0, len(pts)-1, removed)
    if not spans:
        raise ValueError("empty edit")
    cuts = []
    for i, j in spans:
        cuts.append(dict(first_frame=i, end_frame=j, start_ms=pts[i], end_ms=pts[j],
                         last_frame_ms=pts[j]-pts[j-1],
                         first_sample=sample(pts[i]), end_sample=min(sample(pts[j]), len(pcm)//channels)))
    if seam["seam_mode"] == "zero_cross_shift":
        for left, right in zip(cuts, cuts[1:]):
            end, start = left["end_sample"], right["first_sample"]
            search = min(sample(seam["zero_cross_search_ms"]),
                         (end-left["first_sample"]-1)//2, (right["end_sample"]-start-1)//2)
            shift = splice_shift(pcm, channels, end, start, search)
            left["end_sample"] += shift
            right["first_sample"] += shift
    kept = sum(c["end_ms"]-c["start_ms"] for c in cuts)
    plan = dict(contract="pacing-cut-plan@1", keep=cuts, protected=protections,
                long_pause_candidates=flags, cut_count=len(removed), input_ms=pts[-1],
                output_ms=kept, removed_ms=pts[-1]-kept)
    return plan, pts, rate, channels, pcm


def edited_audio(keep, rate, channels, pcm, seam):
    fade = round(rate*seam["micro_fade_ms"]/1000) if seam["seam_mode"] == "micro_fade" else 0
    for index, row in enumerate(keep):
        first, end = row["first_sample"], row["end_sample"]
        n = min(fade, (end-first)//2)
        for pos in range(first, end, 65536):
            stop = min(end, pos+65536)
            samples = array("i", pcm[pos*channels:stop*channels])
            def scale(sample, gain):
                for channel in range(channels):
                    element = (sample-pos)*channels + channel
                    samples[element] = round(samples[element]*gain)
            if index:
                for sample in range(pos, min(stop, first+n)):
                    scale(sample, (sample-first)/max(n-1, 1))
            if index+1 < len(keep):
                for sample in range(max(pos, end-n), stop):
                    scale(sample, (end-1-sample)/max(n-1, 1))
            yield samples


def render(path, dest, plan, rate, channels, pcm, profile, tmp, *, measuring=False):
    keep = plan["keep"]
    raw = Path(tmp) / "audio.raw"
    with raw.open("wb") as out:
        for samples in edited_audio(keep, rate, channels, pcm, profile["audio_seam"]):
            if sys.byteorder != "little":
                samples.byteswap()
            samples.tofile(out)
    select = "+".join(f"between(n,{r['first_frame']},{r['end_frame']-1})" for r in keep)
    offset = "PTS-STARTPTS"
    count = 0
    for a,b in zip(keep, keep[1:]):
        count += a["end_frame"]-a["first_frame"]
        offset += f"-gte(N,{count})*{round(1000*(b['start_ms']-a['end_ms']))}"
    final_index = sum(r["end_frame"]-r["first_frame"] for r in keep)-1
    last_duration = round(keep[-1]["last_frame_ms"]*1000)
    packet_clock = f"setts=duration='if(eq(N,{final_index}),{last_duration},NEXT_PTS-PTS)'"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-f", "s32le", "-ar", str(rate),
           "-ac", str(channels), "-i", str(raw), "-map", "0:v:0", "-map", "1:a:0",
           "-vf", f"settb=expr=1/1000000,select='{select}',setpts='{offset}'",
           "-fps_mode", "passthrough", "-enc_time_base", "1:1000000", "-c:v", "ffv1",
           "-bsf:v", packet_clock, "-c:a", "pcm_s32le", "-map_chapters", "-1", "-f", "matroska", dest]
    run_analysis(cmd) if measuring else run(cmd, quiet=True)


def frame_hashes(path):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0",
           "-fps_mode", "passthrough", "-f", "framemd5", "-"]
    return [s.rsplit(",", 1)[1].strip() for s in run_analysis(cmd).stdout.splitlines() if s and s[0] != "#"]


def verify(source, output, profile, protect, stack):
    plan, pts, rate, ch, pcm = make_plan(source, profile, protect, stack)
    keep = plan["keep"]
    actual_pts = frames(output)
    actual_rate, actual_ch, actual_pcm, _ = sound(output, stack)
    expected_pts, protected, joins = [], [], []
    protected_audio_matches = True
    time = samples = 0
    for index, row in enumerate(keep):
        i, j = row["first_frame"], row["end_frame"]
        for stamp in pts[i:j]:
            expected_pts.append(time+stamp-pts[i])
        for p in plan["protected"]:
            if pts[i] <= p["start_ms"] and p["end_ms"] <= pts[j]:
                first = round(p["start_ms"]*rate/1000)
                end = round(p["end_ms"]*rate/1000)
                dest = samples+first-row["first_sample"]
                protected_audio_matches &= (actual_ch == ch and
                    pcm[first*ch:end*ch] == actual_pcm[dest*ch:(dest+end-first)*ch])
                protected.append((time+p["start_ms"]-pts[i], time+p["end_ms"]-pts[i]))
        time += pts[j]-pts[i]
        samples += row["end_sample"]-row["first_sample"]
        if index+1 < len(keep):
            joins.append(samples)
    removed = subtract(0, len(pts)-1, [(r["first_frame"],r["end_frame"]) for r in keep])
    levels, duration = envelope(output, profile["silence_detection"]["analysis_bandpass_hz"])
    remaining = pauses(levels, duration, profile["silence_detection"])
    uncovered = [piece for a,b in remaining for piece in subtract(a,b,sorted(protected))]
    timing = profile["pacing"]
    source_hashes, output_hashes = frame_hashes(source), frame_hashes(output)
    expected_hashes = [digest for row in keep for digest in source_hashes[row["first_frame"]:row["end_frame"]]]
    expected = hashlib.sha256()
    for block in edited_audio(keep, rate, ch, pcm, profile["audio_seam"]):
        expected.update(block)
    same_samples = expected.digest() == hashlib.sha256(actual_pcm).digest()
    deltas = []
    for join in joins:
        radius = max(1, round(actual_rate*.002))
        diffs = [abs(actual_pcm[k*actual_ch+c]-actual_pcm[(k-1)*actual_ch+c])/2**31
                 for k in range(max(1,join-radius), min(len(actual_pcm)//actual_ch,join+radius+1))
                 for c in range(actual_ch)]
        deltas.append(max(diffs, default=2.0))
    drift = max((abs(a-b) for a,b in zip(expected_pts, actual_pts[:-1])), default=math.inf)
    rules = profile["cut_rules"]
    # The head and tail are evaluated separately from interior pauses.
    checks = dict(residual=all(b-a <= timing["max_keep_silence_ms"] for a,b in uncovered),
                  leading=all(b <= timing["trim_leading_max_ms"] for a,b in uncovered if a == 0),
                  trailing=all(duration-a <= timing["trim_trailing_max_ms"] for a,b in uncovered if b == duration),
                  min_clip_frames=all(r["end_frame"]-r["first_frame"] >= rules["min_clip_frames"] for r in keep),
                  min_removed_frames=all(j-i >= rules["min_removed_frames"] for i,j in removed),
                  protected=len(protected)==len(plan["protected"]) and protected_audio_matches,
                  kept_content=same_samples and expected_hashes==output_hashes,
                  sample_rate=actual_rate==rate and actual_ch==ch,
                  clicks=all(d <= profile["audio_seam"]["max_boundary_sample_delta"] for d in deltas),
                  timestamps=len(actual_pts)-1==len(expected_pts) and drift<=1.01 and abs(actual_pts[-1]-time)<=1.01,
                  audio_duration=abs(len(actual_pcm)/actual_ch/actual_rate*1000-time)<=1.01)
    return dict(checks=checks, verified=all(checks.values()), max_frame_pts_error_ms=drift,
                boundary_sample_deltas=deltas, output_pauses_ms=remaining, cut_plan=plan)


def encode_delivery(master, dest):
    run_analysis(["ffmpeg", "-v", "error", "-nostdin", "-i", master, "-map", "0:v:0", "-map", "0:a:0",
                  "-fps_mode", "passthrough", "-enc_time_base", "1:1000000", "-c:v", "libx264", "-c:a", "aac",
                  "-movflags", "+faststart", dest])


def delivery_checks(master, output):
    def streams(path):
        args = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path]
        return {s["codec_type"]: s for s in json.loads(run_analysis(args).stdout)["streams"]}
    before, after = streams(master), streams(output)
    expected, actual = frames(master), frames(output)
    video, audio = after["video"], after["audio"]
    # Audio duration uses the presentation track, excluding AAC encoder padding.
    return dict(delivery_codecs=(video["codec_name"], audio["codec_name"]) == ("h264", "aac"),
                delivery_geometry=all(video[k] == before["video"][k] for k in ("width", "height")),
                delivery_frames=len(actual)==len(expected) and all(abs(a-b)<=1.01 for a,b in zip(actual, expected)),
                delivery_audio=all(audio[k] == before["audio"][k] for k in ("sample_rate", "channels")),
                delivery_sync=abs(float(audio["start_time"])-float(video["start_time"]))<=.00101 and
                              abs(float(audio["duration"])*1000-expected[-1])<=1.1)


def verify_delivery(source, output, profile, protect, stack):
    with tempfile.TemporaryDirectory() as tmp:
        master = str(Path(tmp)/"expected.mkv")
        plan, _, rate, channels, pcm = make_plan(source, profile, protect, stack)
        render(source, master, plan, rate, channels, pcm, profile, tmp, measuring=True)
        result = verify(source, master, profile, protect, stack)
        expected = str(Path(tmp)/"expected.mp4")
        encode_delivery(master, expected)
        checks = delivery_checks(master, output)
        checks["delivery_picture_content"] = frame_hashes(expected) == frame_hashes(output)
        with decoded_pcm(expected, [], "s32le", "i") as ref, decoded_pcm(output, [], "s32le", "i") as actual:
            checks["delivery_audio_content"] = hashlib.sha256(ref).digest() == hashlib.sha256(actual).digest()
        result["checks"].update(checks)
        result["verified"] = all(result["checks"].values())
        return result


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def cli(args, checking=False):
    with ExitStack() as stack:
        return _cli(args, checking, stack)


def _cli(args, checking, stack):
    try:
        profile = read_profile(args.profile) if args.profile else None
        if not checking and not args.extract_profile and not profile:
            raise ValueError("--references or --protect-ranges requires a pacing mode")
        if checking and (not profile or not args.source or len(args.paths) != 1):
            raise ValueError("verify requires one output, --profile and --source")
        if not checking and args.extract_profile and (profile or args.protect_ranges):
            raise ValueError("profile extraction cannot apply an edit")
        if not checking and args.references and not args.extract_profile:
            raise ValueError("--references requires --extract-profile")
        allowed = {"--profile", "--protect-ranges", "--json", "--json-brief", "--dry-run", "--timeout"}
        allowed.update({"--source"} if checking else {"-o", "--output", "--overwrite", "--extract-profile", "--references", "--max-cuts"})
        if profile and not checking:
            allowed.add("--plan")
        for token in sys.argv[1:]:
            if token == "--":
                break
            if token.startswith("-") and token.split("=", 1)[0] not in allowed:
                raise ValueError("unsupported option in pacing mode: " + token)
        inputs = [args.source, *args.paths] if checking else [args.input, *(args.references or [])]
        for path in inputs:
            if not Path(path).is_file():
                raise ValueError("missing local media: " + path)
        if checking:
            gate = verify_delivery if Path(args.paths[0]).suffix.lower() == ".mp4" else verify
            result = gate(args.source, args.paths[0], profile, args.protect_ranges, stack)
            if not result["verified"]:
                die("pacing verification failed", kind="verification", output=None, **result)
            print_json(dict(status="completed", dry_run=STATE.dry_run, output=None, commands=list(STATE.commands), **result))
            return 0 if result["verified"] else 1
        dest = args.output
        if STATE.plan and not dest:
            raise ValueError("saving a replayable pacing plan requires -o OUTPUT.mkv")
        if not dest and not (args.extract_profile or STATE.dry_run):
            raise ValueError("supply -o OUTPUT.mkv for the lossless pacing master")
        if dest:
            extension = Path(dest).suffix.lower()
            if extension not in ((".json",) if args.extract_profile else (".mkv", ".mp4")):
                raise ValueError("expected a JSON profile or a .mkv/.mp4 media output")
            guard_sidecar(dest, *inputs, args.profile, args.protect_ranges)
        if args.extract_profile:
            report = dict(profile=extract(inputs))
        else:
            plan, _, rate, channels, pcm = make_plan(args.input, profile, args.protect_ranges, stack)
            if not STATE.dry_run and plan["cut_count"] > args.max_cuts:
                raise ValueError("pacing edit exceeds --max-cuts")
            expected = os.environ.get("FFMPEG_SKILL_PACING_PLAN_SHA256")
            if expected and expected != plan_digest(plan):
                raise ValueError("measured pacing plan differs from the reviewed frame/sample ranges")
            report = dict(cut_plan=plan)
            if STATE.plan:
                for item in [*inputs, args.protect_ranges, args.profile]:
                    if item and Path(item).is_file():
                        register_plan_input(item)
                report["plan"] = write_plan(STATE.plan, dest, report)
        if dest and not STATE.dry_run:
            with tempfile.TemporaryDirectory(dir=Path(dest).resolve().parent) as tmp:
                staged = str(Path(tmp)/("master" + extension))
                if args.extract_profile:
                    Path(staged).write_text(json.dumps(report["profile"], allow_nan=False, indent=2)+"\n", encoding="utf-8")
                else:
                    staged = str(Path(tmp)/"master.mkv")
                    render(args.input, staged, plan, rate, channels, pcm, profile, tmp)
                    with ExitStack() as verification_stack:
                        gate = verify(args.input, staged, profile, args.protect_ranges, verification_stack)
                    if not gate["verified"]:
                        die("pacing verification failed before publication", kind="verification", output=None, **gate)
                    if extension == ".mp4":
                        delivery = str(Path(tmp)/"delivery.mp4")
                        encode_delivery(staged, delivery)
                        checks = delivery_checks(staged, delivery)
                        if not all(checks.values()):
                            die("pacing delivery failed before publication", kind="verification", checks=checks)
                        gate["checks"].update(checks)
                        staged = delivery
                    report["verification"] = [dict(step=k, ok=v) for k, v in gate["checks"].items()]
                if STATE.overwrite:
                    from _common.runner import refuse_changed_output
                    refuse_changed_output(dest)
                    os.replace(staged, dest)
                else:
                    os.link(staged, dest)
        print_json(dict(status="completed", output=None if STATE.dry_run else dest, dry_run=STATE.dry_run,
                        verified="verification" in report, commands=list(STATE.commands), **report))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        die(str(exc), kind="input")
