"""Downloads a local model into Comprsly's model folder.

    python tools_download_model.py qwen2.5-1.5b
    python tools_download_model.py --list

The shipped app downloads the current model itself since 2026-07-22 (the
first-run onboarding and the Settings AI page, via
local_model.request_download). This script is the developer-side path: it
can pull ANY entry in SOURCES by hand -- notably the phi3-mini rollback,
which the app has no button for. Once the files land,
local_model.active_spec() picks the new model up automatically on the next
load, no code change and no reinstall.

Provenance note, deliberate and worth keeping in mind: there is no
first-party Microsoft or Qwen CPU int4 ONNX build of Qwen2.5. The source
below is a community Olive build. ONNX graphs are data, not pickles, so
there is no code-execution path here the way there would be with a .bin
torch checkpoint, but the build quality is unverified until it is actually
run against real prompts.
"""
import os
import shutil
import sys

SOURCES = {
    "qwen2.5-1.5b": {
        "repo": "khanuckaeff/Qwen2.5-1.5B-Instruct-Olive-Onnx",
        "subfolder": "cpu_and_mobile",
        "dest_name": "qwen2.5-1.5b-instruct-int4-cpu",
        "approx_mb": 1021,
        "why": "CURRENT. int4 CPU, 28 KB/token KV cache, 32k context, IFEval 42.5",
    },
    # Kept purely as a rollback path. Phi-3 was removed from disk 2026-07-21
    # after Qwen2.5-1.5B beat it on speed and on the exact prompts it kept
    # failing (Build.md §5). This entry means that decision costs one command
    # to undo rather than being a one-way door. Official Microsoft repo.
    "phi3-mini": {
        "repo": "microsoft/Phi-3-mini-4k-instruct-onnx",
        "subfolder": "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
        "dest_name": os.path.join("cpu_and_mobile", "cpu-int4-rtn-block-32-acc-level-4"),
        "approx_mb": 2540,
        "why": "ROLLBACK ONLY. The previous model, 2.5 GB, 4k context, slower",
    },
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--list", "-l", "-h", "--help"):
        print("Available:")
        for key, s in SOURCES.items():
            print(f"  {key:<16} {s['repo']}  ~{s['approx_mb']} MB\n"
                  f"  {'':<16} {s['why']}")
        return 0

    key = sys.argv[1]
    if key not in SOURCES:
        print(f"unknown model '{key}', try --list")
        return 1
    src = SOURCES[key]

    root = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Comprsly", "model")
    dest = os.path.join(root, src["dest_name"])
    if os.path.isdir(dest) and os.listdir(dest):
        print(f"{dest} already exists and is not empty, nothing to do.")
        return 0

    from huggingface_hub import snapshot_download

    print(f"downloading {src['repo']} (~{src['approx_mb']} MB) -> {dest}")
    staged = snapshot_download(
        repo_id=src["repo"],
        allow_patterns=[f"{src['subfolder']}/*"] if src["subfolder"] else None,
    )
    staged_dir = os.path.join(staged, src["subfolder"]) if src["subfolder"] else staged

    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(staged_dir):
        s = os.path.join(staged_dir, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, name))

    total = sum(os.path.getsize(os.path.join(dest, f)) for f in os.listdir(dest))
    print(f"done, {total / 1e6:.0f} MB in {dest}")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import local_model
    print(f"local_model now resolves to: {local_model.model_label()}")
    print(f"  {local_model.model_dir()}")
    if not local_model.is_model_downloaded():
        print("  WARNING: the expected model file is missing, check the spec's "
              "'filename' against what actually landed above")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
