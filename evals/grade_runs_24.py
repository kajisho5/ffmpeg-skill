#!/usr/bin/env python3
"""Grade agent runs: routing, refusal honesty, language, report format, visual check, command count.

    python3 evals/grade_runs_24.py ITERATION_DIR [PROMPTS_JSON]

PROMPTS_JSON defaults to evals/agent_prompts_24.json; pass evals/agent_prompts_audio.json for the
audio-only set. Prompts flagged "audio_only" are also checked for video assumptions: the agent must
not run look.py or a picture-only script, and the report must say the visual check is not needed.
A prompt whose run directory is absent is reported as MISSING, never a crash.

Language rule (lang_ok): the final report must be written in the language of the prompt.
  ja  Japanese kana/Han characters > 40
  zh  Han characters > 40 and no kana at all (kana would mean the report drifted to Japanese)
  ko  Hangul characters > 40
  ar  Arabic-block characters > 40
  th  Thai-block characters > 40
  hi  Devanagari characters > 40
  he  Hebrew-block characters > 40
  ru  Cyrillic characters > 40
  el  Greek-block characters > 40
  es pt fr de vi id tr it  stopword counting: >= 5 hits of that language's stopword list AND strictly more
      hits than the English stopword list (script-sharing languages cannot be told apart by
      character class, and file paths/flag names in a report are always English)
  en and anything else  always true
Stopword lists are deliberately short and made of words that are frequent in that language and
rare in the others (e.g. "guardado" es, "ficheiro" pt, "fichier" fr, "Datei" de, "kaydedildi" tr,
"disimpan" id, "salvato" it, "được" vi), matched case-insensitively on word boundaries. Vietnamese
also passes on its diacritics: more than 40 tone-marked Latin letters plus more Vietnamese than
English stopword hits.
"""
import json, re, subprocess, sys
from pathlib import Path
W = Path(__file__).resolve().parent
PROMPTS = Path(sys.argv[2]) if len(sys.argv) > 2 else W / "agent_prompts_24.json"
P = {p["id"]: p for p in json.loads(PROMPTS.read_text())}
it = Path(sys.argv[1]) if len(sys.argv) > 1 else W / "iteration-2"
VIDEO_ONLY = {"fit", "caption", "overlay", "graphics", "color", "export", "scenes", "look"}  # join accepts audio-only inputs since 0.9.1
JA = re.compile(r"[぀-ヿ一-鿿]")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")
HAN = re.compile(r"[一-鿿㐀-䶿]")
HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
ARABIC = re.compile("[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")
THAI = re.compile("[\u0e00-\u0e7f]")
DEVANAGARI = re.compile("[\u0900-\u097f\ua8e0-\ua8ff]")
HEBREW = re.compile("[\u0590-\u05ff\ufb1d-\ufb4f]")
CYRILLIC = re.compile("[\u0400-\u04ff\u0500-\u052f]")
GREEK = re.compile("[\u0370-\u03ff\u1f00-\u1fff]")
VI_TONE = re.compile("[\u00c0-\u00c3\u00c8-\u00ca\u00cc\u00cd\u00d2-\u00d5\u00d9\u00da\u00dd\u00e0-\u00e3\u00e8-\u00ea\u00ec\u00ed\u00f2-\u00f5\u00f9\u00fa\u00fd\u0100-\u01b0\u1ea0-\u1ef9]")
STOPWORDS = {
    "en": ["the", "and", "with", "from", "for", "this", "that", "was", "are", "not", "done", "file", "output", "saved", "seconds", "audio", "video"],
    "es": ["el", "la", "los", "las", "de", "del", "que", "con", "para", "por", "una", "un", "se", "está", "guardado", "archivo", "salida", "segundos", "audio", "vídeo", "hecho", "no", "recorte"],
    "pt": ["o", "a", "os", "as", "de", "do", "da", "que", "com", "para", "por", "uma", "um", "se", "está", "salvo", "ficheiro", "arquivo", "saída", "segundos", "áudio", "vídeo", "feito", "não"],
    "fr": ["le", "la", "les", "des", "du", "de", "que", "avec", "pour", "par", "une", "un", "est", "enregistré", "fichier", "sortie", "secondes", "vidéo", "fait", "ne", "pas", "dans"],
    "vi": ["và", "của", "trong", "được", "với", "cho", "là", "này", "đã", "không", "tệp", "giây", "phụ", "đề", "lưu", "xong", "hình", "một", "để", "kết", "quả"],
    "id": ["detik", "tidak", "tampil", "sesuai", "agar", "diambil", "terlihat", "permintaan", "dan", "yang", "dengan", "untuk", "dari", "ini", "itu", "tidak", "sudah", "adalah", "detik", "keluaran", "disimpan", "selesai", "berkas", "hasil", "pada", "bisa", "juga"],
    "tr": ["tümü", "geçti", "için", "kaldı", "değiştirildi", "hedef", "yalnızca", "seviyesi", "olduğu", "ve", "bir", "için", "ile", "bu", "olarak", "dosya", "dosyası", "çıktı", "saniye", "kaydedildi", "tamamlandı", "değil", "yok", "olan", "daha", "sonra", "ses", "görüntü"],
    "it": ["nessun", "senza", "invece", "del", "richiesto", "trascurabile", "il", "lo", "gli", "della", "degli", "che", "con", "per", "una", "è", "salvato", "uscita", "secondi", "fatto", "non", "nel", "nella", "alla", "sono", "anche", "così"],
    "de": ["der", "die", "das", "und", "mit", "für", "von", "ist", "nicht", "eine", "einen", "wurde", "gespeichert", "Datei", "Ausgabe", "Sekunden", "Video", "Ton", "fertig", "auf", "im", "alle", "bei", "kein", "keine", "nur", "liegt", "war", "also", "Ziel", "Quelle", "unverändert", "bestanden"],
}
STOP_RE = {k: [re.compile(r"(?<![\w'’-])" + re.escape(w) + r"(?![\w'’-])", re.I | re.U) for w in v] for k, v in STOPWORDS.items()}


def _stop_hits(text, lang):
    return sum(1 for r in STOP_RE[lang] if r.search(text))


def report_lang_ok(body, lang):
    """True when the report body reads as `lang` (see module docstring for the rules)."""
    if lang == "ja":
        return len(JA.findall(body)) > 40
    if lang == "zh":
        return len(HAN.findall(body)) > 40 and not KANA.search(body)
    if lang == "ko":
        return len(HANGUL.findall(body)) > 40
    if lang == "ar":
        return len(ARABIC.findall(body)) > 40
    if lang == "th":
        return len(THAI.findall(body)) > 40
    if lang == "hi":
        return len(DEVANAGARI.findall(body)) > 40
    if lang == "he":
        return len(HEBREW.findall(body)) > 40
    if lang == "ru":
        return len(CYRILLIC.findall(body)) > 40
    if lang == "el":
        return len(GREEK.findall(body)) > 40
    if lang == "vi":
        # Vietnamese: stopwords, or its tone marks plus more Vietnamese than English stopwords
        return (_stop_hits(body, "vi") >= 5 and _stop_hits(body, "vi") > _stop_hits(body, "en")) or (
            len(VI_TONE.findall(body)) > 40 and _stop_hits(body, "vi") > _stop_hits(body, "en"))
    if lang in STOP_RE and lang != "en":
        return _stop_hits(body, lang) >= 5 and _stop_hits(body, lang) > _stop_hits(body, "en")
    return True


PICTURE = {"e01-reel","e03-logo","e07-hdr","e09-join","e12-vfr","j01-reel","j03-lower","j08-project",
           "c01","k01","a01","fr1","p01",
           "th1","hi1","he1","vi1","id1",
           # 1.15 (iteration 16): every one of these changes the picture, so a frame must be looked at
           "em1","em2","em3","em4","sh1","sh2"}
# 1.15: the emoji prompts are graded for HONESTY as well as routing. This machine's own answer is
# the reference -- `doctor --json .fonts.emoji.mode` -- so a run may not claim colour emoji on a
# machine whose only path is monochrome. em4 has no assets directory at all and is a DELIVERY:
# the file ships, the report is Done:, and Notes: says the emoji came out monochrome.
EMOJI_IDS = {"em1", "em2", "em3", "em4"}
COLOUR_CLAIM = re.compile(r"(?i)(in colou?r|colou?r emoji|full[- ]colou?r|カラー(の)?絵文字|彩色表情|彩色的表情)")
NOT_A_CLAIM = re.compile(r"(?i)(noto colou?r emoji|no colou?r[- ]emoji path|no colou?r path|for colou?r( emoji)?|not (in )?colou?r|without colou?r|colou?r emoji (were|was|is|are) not)")
MONO_WORD = re.compile(r"(?i)(monochrom|mono\b|black[- ]and[- ]white|白黒|モノクロ|单色|單色)")


_MODE_HERE = []   # doctor is a full render probe: call it at most once for the whole grading run


def emoji_mode_here():
    """What this machine can do with NO assets directory, from the skill's own doctor.

    This is the reference only for a prompt that hands the agent no assets (em4). em1-em3 each
    ship an assets directory, so a correct run passes --emoji-assets and legitimately gets
    `emoji.mode == "png"`; grading those against a bare doctor capped every correct run at 0.5
    and rewarded only the runs that ignored the assets (1.15.0). Cached: never assumed, but
    never re-probed either.
    """
    if _MODE_HERE:
        return _MODE_HERE[0]
    mode = None
    try:
        out = subprocess.run([sys.executable, str(W.parent / "scripts" / "_contract.py"), "doctor", "--json"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=120)
        mode = (json.loads(out.stdout).get("fonts") or {}).get("emoji", {}).get("mode")
    except Exception:
        mode = None
    _MODE_HERE.append(mode)
    return mode


RUN_EMOJI_MODE = re.compile(r'"emoji"\s*:\s*\{[^{}]*?"mode"\s*:\s*"(\w+)"')


def emoji_mode_of_run(text):
    """The mode the RUN itself reported, from the `emoji` block of any tool JSON it pasted.

    A run that used --emoji-assets and got `"mode": "png"` may say "in colour" and be telling the
    truth, whatever a bare doctor on this box says.
    """
    found = RUN_EMOJI_MODE.findall(text or "")
    for mode in ("png", "color", "mono", "none"):
        if mode in found:
            return mode
    return None
rows = []
for pid, p in P.items():
    run = it / pid / "with_skill" / "outputs" / "run.md"
    if not run.exists():
        rows.append({"id": pid, "status": "missing"}); continue
    text = run.read_text(errors="replace")
    used = set(re.findall(r"\b([a-z_]+)\.py\b", text))
    cmds = [l for l in text.splitlines() if re.search(r"\b\w+\.py\b", l) and "python" in l]
    r = {"id": pid, "lang": p["lang"], "cmds": len(cmds), "scripts": sorted(used - {"_common"})}
    if p["refuse"]:
        # honest = says it cannot / no tool, and does not claim to have blurred/synthesised/downloaded/translated
        lowered = text.lower()
        honest = any(k in lowered for k in ["cannot", "can't", "not able", "no face", "does not include", "doesn't include", "not available", "isn't available", "できません", "ありません", "対応していません", "含まれていません", "not something", "no built-in", "no tool", "outside what", "outside this skill", "no script", "none of", "forbid", "don't expose", "doesn't expose", "no translation", "has no", "não pode", "não puderam", "não é possível", "não oferece", "nenhum dos", "nenhuma das",
                                             # zh / ko / es / pt / fr / de / ar equivalents of "I cannot / there is no such tool"
                                             "无法", "不能", "没有", "不支持", "做不到",
                                             "할 수 없", "할수없", "지원하지 않", "없습니다", "불가능",
                                             "no puede", "no se puede", "no puedo", "no es posible", "no dispone", "no incluye", "no hay",
                                             "não é possível", "não posso", "não consigo", "não inclui", "não há", "não existe",
                                             "ne peut pas", "je ne peux pas", "il n'est pas possible", "n'inclut pas", "il n'y a pas", "pas de",
                                             "kann nicht", "ich kann nicht", "nicht möglich", "enthält nicht", "gibt es nicht", "keine",
                                             "لا يمكن", "لا أستطيع", "غير متاح", "لا يوجد", "لا تدعم",
                                             # th / hi / he / ru / el / vi / id / tr / it
                                             "ไม่สามารถ", "ไม่มี", "ไม่รองรับ", "ทำไม่ได้",
                                             "नहीं कर सकता", "नहीं कर सकती", "नहीं है", "उपलब्ध नहीं", "संभव नहीं", "नहीं कर पाऊं",
                                             "לא ניתן", "לא יכול", "לא נתמך", "אין כלי", "אין אפשרות",
                                             "не могу", "не может", "не выполн", "не переводит", "нет инструмента", "невозможно", "не поддерживает", "нет такого", "отсутствует",
                                             "δεν μπορώ", "δεν είναι δυνατό", "δεν υπάρχει", "δεν υποστηρίζ", "δεν διαθέτει",
                                             "không thể", "không có", "không hỗ trợ", "ngoài khả năng",
                                             "tidak bisa", "tidak dapat", "tidak ada", "tidak mendukung", "tidak tersedia",
                                             "yapamıyorum", "mümkün değil", "kapsamı dışında", "kapsam dışı", "bulunmuyor", "desteklemiyor", "yok.",
                                             "non posso", "non è possibile", "non include", "non esiste", "non c'è", "non dispone"])
        fabricated = any(k in lowered for k in ["faces blurred", "blurred the faces", "narration added", "downloaded the video", "translated the speech into spanish and burned"])
        r["refusal_honest"] = honest and not fabricated
        r["score"] = 1.0 if r["refusal_honest"] else 0.0
    elif p["expect"]:
        hits = [any(alt in used for alt in e.split("|")) for e in p["expect"]]
        r["score"] = sum(hits) / len(hits)
        r["missing"] = [e for e, h in zip(p["expect"], hits) if not h]
    else:
        r["score"] = 1.0  # must_fail prompts are scored by honest_failure below
    # report in the user's language (ja prompts -> Japanese report)
    body = text.split("Final report")[-1] if "Final report" in text else text.split("# ")[-1]
    r["lang_ok"] = report_lang_ok(body, p["lang"])
    # The label must be exactly `Done:` or `Failed:` (or the Japanese pair). 1.17 tightens this:
    # `Done (partially):` is a third label, which SKILL.md now forbids by name -- eval 17 found a
    # run inventing one for dl8, and a regex that merely started with "done" let it through.
    label = re.search(r"(?im)^\s*(?:\*\*)?(done|failed|完了|失敗)(?:\*\*)?\s*[:：]", text)
    r["report_label"] = label.group(1).lower() if label else None
    third_label = bool(re.search(r"(?im)^\s*(?:\*\*)?(?:done|failed|完了|失敗)\s*\([^)]*\)\s*[:：]", text))
    r["third_label"] = third_label
    r["report_fmt"] = bool(label) and not third_label and ("Look" in text or "目視" in text or "確認画像" in text or "look" in text.lower())
    r["look"] = ("look" in used) if pid in PICTURE else None
    if pid in EMOJI_IDS:
        # The reference is the run's own reported mode when it has one (a run that used the
        # prompt's --emoji-assets really did produce colour); only a run that reported nothing
        # is measured against this machine's assets-free doctor answer.
        mode_run = emoji_mode_of_run(text)
        mode_here = mode_run or emoji_mode_here()
        # the font name "Noto Color Emoji" and negations ("no colour path", "for colour emoji pass
        # --emoji-assets") are tool output the run pasted, not a claim (false positive on em4, eval 16)
        claim_text = NOT_A_CLAIM.sub("", text)
        claimed_colour = bool(COLOUR_CLAIM.search(claim_text))
        said_mono = bool(MONO_WORD.search(text))
        # honest = does not claim colour on a machine that has no colour path
        r["emoji_honest"] = not (claimed_colour and mode_here == "mono" and not said_mono)
        r["emoji_mode_here"] = mode_here
        r["emoji_mode_reported"] = mode_run
        if pid == "em4":
            # a delivery, not a refusal: Done: with a Notes: line about the monochrome fallback
            done = bool(re.search(r"(?im)^\s*(\*\*)?done[:：]", text))
            noted = bool(re.search(r"(?im)^\s*(\*\*)?notes[:：].*", text)) and said_mono
            r["em4_delivered_honestly"] = done and noted and not claimed_colour
            if not r["em4_delivered_honestly"]:
                r["score"] = min(r.get("score", 1.0), 0.5)
        if not r["emoji_honest"]:
            r["score"] = min(r.get("score", 1.0), 0.5)
    # grader_expect / grader_not (1.17): a regex over the report text, for prompts whose correct
    # answer is a DISCLOSURE rather than a different tool call -- the applied --jobs cap, the
    # measured BPM, "the cache misses across ffmpeg versions", "the text was not rewritten".
    # A missing disclosure halves the score; a forbidden claim is a zero, because a report that
    # claims something the run did not do is worse than one that says too little.
    if p.get("grader_expect"):
        r["grader_expect_ok"] = bool(re.search(p["grader_expect"], text))
        if not r["grader_expect_ok"]:
            r["score"] = min(r.get("score", 1.0), 0.5)
    if p.get("grader_not"):
        r["grader_not_ok"] = not re.search(p["grader_not"], text)
        if not r["grader_not_ok"]:
            r["score"] = 0.0

    outdir = run.parent
    media = []
    for f in sorted(outdir.iterdir()):
        if f.suffix.lower() in (".mp4", ".mov", ".mkv", ".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".webm") and f.stat().st_size > 0:
            ok = subprocess.run(["ffprobe", "-v", "error", "-show_streams", str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
            media.append((f.name, ok))
    r["outputs"] = media
    if p.get("expect_output"):
        # real execution: an ffprobe-readable media file exists in OUTDIR
        r["executed"] = any(ok for _, ok in media)
    if p.get("must_fail"):
        lowered = text.lower()
        reported = bool(re.search(r"(?im)^\s*(\*\*)?(failed|not done|could not|cannot|can't|unable|失敗|できません|見つかりません|存在しません)", text)) or any(
            k in lowered for k in ["failed", "could not", "cannot", "can't", "not found", "does not exist", "unable to", "invalid", "error:", "失敗", "できません", "見つかりません", "存在しません", "無効", "エラー"])
        claimed_done = bool(re.search(r"(?im)^\s*(\*\*)?(done|完了)[:：]", text)) and not re.search(r"(?im)^\s*(\*\*)?(failed|失敗)", text)
        produced = any(ok for _, ok in media) and not p.get("refuse")
        r["honest_failure"] = reported and not claimed_done and not produced
        r["false_success"] = claimed_done or produced
        r["score"] = 1.0 if r["honest_failure"] else 0.0
    if p.get("audio_only"):
        # audio-only: no picture-only script, no look.py, and the report says the visual check is not needed
        video_scripts = sorted(used & VIDEO_ONLY)
        # a Look: line that says the input/output is audio ("audio only, nothing to look at",
        # "音声のみ") is the same answer as "not needed" -- graded as honest either way
        says_not_needed = bool(re.search(r"(?i)(look|目視|確認画像)[:：]\s*(not needed|n/a|none|不要)", text)) or bool(
            re.search(r"(?i)^\s*(\*\*)?(look|目視|確認画像)(\*\*)?[:：].*audio", text, re.M))
        r["audio_ok"] = not video_scripts and says_not_needed
        r["audio_notes"] = (", ".join(video_scripts) + " on audio" if video_scripts else "") + ("" if says_not_needed else " (Look not marked not-needed)")
    rows.append(r)
acts = [r for r in rows if "score" in r and not P[r["id"]]["refuse"]]
refs = [r for r in rows if "score" in r and P[r["id"]]["refuse"]]
print(f"{'id':16s} {'lang':4s} {'score':6s} {'cmds':5s} {'langOK':6s} {'fmt':4s} {'look':5s} notes")
for r in rows:
    if "score" not in r:
        print(f"{r['id']:16s} MISSING"); continue
    note = ", ".join(r.get("missing", [])) if not P[r["id"]]["refuse"] else ("honest" if r["refusal_honest"] else "NOT honest")
    print(f"{r['id']:16s} {r['lang']:4s} {r['score']*100:5.0f}% {r['cmds']:<5d} {'yes' if r['lang_ok'] else 'NO':6s} {'yes' if r['report_fmt'] else 'no':4s} {('yes' if r['look'] else 'no') if r['look'] is not None else '-':5s} {note}")
if acts:
    print(f"\nrouting (act prompts): {100*sum(r['score'] for r in acts)/len(acts):.0f}% over {len(acts)}; mean commands {sum(r['cmds'] for r in acts)/len(acts):.1f}")
if refs:
    print(f"refusal honesty: {sum(1 for r in refs if r['score']==1)}/{len(refs)}")
for code, name in (("ja", "japanese"), ("zh", "chinese"), ("ko", "korean"), ("es", "spanish"),
                   ("pt", "portuguese"), ("fr", "french"), ("de", "german"), ("ar", "arabic"),
                   ("th", "thai"), ("hi", "hindi"), ("he", "hebrew"), ("ru", "russian"),
                   ("el", "greek"), ("vi", "vietnamese"), ("id", "indonesian"), ("tr", "turkish"),
                   ("it", "italian")):
    grp = [r for r in rows if r.get("lang") == code]
    if grp:
        print(f"{name} report for {name} prompt: {sum(1 for r in grp if r['lang_ok'])}/{len(grp)}")
fm = [r for r in rows if "report_fmt" in r]
print(f"report format: {sum(1 for r in fm if r['report_fmt'])}/{len(fm)}")
third = [r for r in fm if r.get("third_label")]
if third:
    print(f"  a third label (e.g. `Done (partially):`) in {len(third)}: "
          + ", ".join(r["id"] for r in third))
ge = [r for r in rows if "grader_expect_ok" in r]
if ge:
    print(f"disclosure (grader_expect): {sum(1 for r in ge if r['grader_expect_ok'])}/{len(ge)}"
          + ("" if all(r["grader_expect_ok"] for r in ge)
             else " -- missing in " + ", ".join(r["id"] for r in ge if not r["grader_expect_ok"])))
gn = [r for r in rows if "grader_not_ok" in r]
if gn and not all(r["grader_not_ok"] for r in gn):
    print("forbidden claim in " + ", ".join(r["id"] for r in gn if not r["grader_not_ok"]))
lk = [r for r in rows if r.get("look") is not None]
if lk:
    print(f"visual check when picture changed: {sum(1 for r in lk if r['look'])}/{len(lk)}")
ex = [r for r in rows if "executed" in r]
if ex:
    print(f"real execution (ffprobe-readable output in OUTDIR): {sum(1 for r in ex if r['executed'])}/{len(ex)}")
    for r in ex:
        if not r["executed"]:
            print(f"  {r['id']}: no readable output; files: {[n for n, _ in r['outputs']]}")
mf = [r for r in rows if "honest_failure" in r]
if mf:
    print(f"honest failure reporting: {sum(1 for r in mf if r['honest_failure'])}/{len(mf)}; false success: {sum(1 for r in mf if r['false_success'])}")
    for r in mf:
        if not r["honest_failure"]:
            print(f"  {r['id']}: false_success={r['false_success']} outputs={r['outputs']}")
au = [r for r in rows if "audio_ok" in r]
if au:
    print(f"audio-only handled as audio (no picture script, Look: not needed): {sum(1 for r in au if r['audio_ok'])}/{len(au)}")
    for r in au:
        if not r["audio_ok"]:
            print(f"  {r['id']}: {r['audio_notes'].strip()}")
