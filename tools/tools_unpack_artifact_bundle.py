"""Unpacks a Claude Artifacts "bundler" export (what you get when you download
an Artifact as .html from Claude Design/claude.ai) into a real, deployable
static site: a clean index.html with no leftover placeholders, plus a real
assets/ folder of actual files (images, JS libraries) -- no blob: URLs, no
in-browser unpacking step needed.

Real problem this solves (2026-07-26): the exported .html is NOT plain HTML.
It's a small loader page (title "Bundled Page", "Unpacking...") that only
becomes the real page once its own JS runs client-side: a
<script type="__bundler/manifest"> holds every image/JS asset as base64
(optionally gzip'd), and a <script type="__bundler/template"> holds the
final HTML as a JSON-encoded string with the assets' uuids as placeholders.
The loader's JS decodes all of that into blob: URLs and swaps the live DOM.
That's fine for viewing once in a browser, but blob: URLs cannot survive
being written to disk and served from Apache later -- they're
tab-session-scoped. This script does the same decode the JS does, in plain
Python, and writes real files instead of blob URLs, so the output is
something you can scp straight into a docroot.

Usage:
    python tools_unpack_artifact_bundle.py "path/to/Downloaded Artifact.html" out_dir/

Writes out_dir/index.html + out_dir/assets/<hash>.<ext> for every embedded
asset. Also handles the ext_resources mapping (e.g. the exported page
pinning specific unpkg.com React/ReactDOM builds -- window.__resources maps
those CDN URLs to the local downloaded copies, same as the loader's own
injected script, so the page prefers the bundled local copy over hitting
the CDN at runtime).

Does NOT handle nested page bundles (iframe-embedded child artifacts,
manifest key __bundler/page_order) -- none seen in practice for Comprsly's
marketing site or privacy policy exports, both single-page. If page_order
is ever non-empty, this script will silently skip those manifest entries as
assets (correct) but won't mint real frames for them -- would need
extending if that ever comes up.

Real deploy history: used 2026-07-26 to ship both comprsly.com's homepage
and /privacy/ page from Claude Design exports. Re-run this exact script
for any future website update -- see Build.md's RESUME POINT / website
section for the full deploy steps (scp to the Pi, chown www-data, backup
first).
"""
import re
import json
import base64
import gzip
import os
import sys
import hashlib


def extract_script(html, type_attr):
    m = re.search(
        r'<script type="' + re.escape(type_attr) + r'">(.*?)</script>',
        html, re.DOTALL
    )
    if not m:
        return None
    return m.group(1)


EXT_BY_MIME = {
    "text/css": "css",
    "text/javascript": "js",
    "application/javascript": "js",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/x-icon": "ico",
    "font/woff2": "woff2",
    "font/woff": "woff",
    "font/ttf": "ttf",
    "application/font-woff": "woff",
    "application/octet-stream": "bin",
    "text/html": "html",
    "text/plain": "txt",
}


def unpack(src_path, out_dir, asset_subdir="assets"):
    with open(src_path, "r", encoding="utf-8") as f:
        html = f.read()

    manifest_raw = extract_script(html, "__bundler/manifest")
    template_raw = extract_script(html, "__bundler/template")
    ext_res_raw = extract_script(html, "__bundler/ext_resources")
    page_order_raw = extract_script(html, "__bundler/page_order")

    if manifest_raw is None or template_raw is None:
        print(f"  FAILED: missing manifest or template in {src_path} "
              f"(not a bundler export? plain HTML doesn't need this script)")
        return None

    manifest = json.loads(manifest_raw)
    template = json.loads(template_raw)  # template script content is a JSON-encoded STRING
    ext_resources = json.loads(ext_res_raw) if ext_res_raw else []
    page_order = json.loads(page_order_raw) if page_order_raw else []
    page_set = set(page_order)

    os.makedirs(os.path.join(out_dir, asset_subdir), exist_ok=True)

    uuid_to_relpath = {}
    for uuid, entry in manifest.items():
        if uuid in page_set:
            continue  # nested page text, not a real asset file -- see docstring caveat
        data_b64 = entry["data"]
        mime = entry.get("mime", "application/octet-stream")
        compressed = entry.get("compressed", False)

        raw_bytes = base64.b64decode(data_b64)
        if compressed:
            raw_bytes = gzip.decompress(raw_bytes)

        ext = EXT_BY_MIME.get(mime, "bin")
        # Short, stable, content-addressed filename instead of the raw uuid,
        # purely cosmetic (shorter URLs in the deployed HTML).
        short = hashlib.sha1(uuid.encode()).hexdigest()[:10]
        fname = f"{short}.{ext}"
        fpath = os.path.join(out_dir, asset_subdir, fname)
        with open(fpath, "wb") as af:
            af.write(raw_bytes)
        uuid_to_relpath[uuid] = f"{asset_subdir}/{fname}"

    # Substitute every uuid occurrence in the template with its real relative path.
    for uuid, relpath in uuid_to_relpath.items():
        template = template.replace(uuid, relpath)

    # ext_resources: map external resource id -> real relative asset path,
    # matching the loader's window.__resources injection, in case any inline
    # script in the page references window.__resources[...] at runtime
    # (e.g. preferring a locally-bundled React over fetching unpkg.com).
    resource_map = {}
    for entry in ext_resources:
        u = entry.get("uuid")
        if u in uuid_to_relpath:
            resource_map[entry["id"]] = uuid_to_relpath[u]
    if resource_map:
        resource_script = (
            "<script>window.__resources = "
            + json.dumps(resource_map).replace("</", "<\\/")
            + ";</script>"
        )
        m = re.search(r"<head[^>]*>", template, re.IGNORECASE)
        if m:
            i = m.end()
            template = template[:i] + resource_script + template[i:]

    out_html_path = os.path.join(out_dir, "index.html")
    with open(out_html_path, "w", encoding="utf-8") as f:
        f.write(template)

    remaining_uuids = re.findall(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", template
    )
    print(f"  wrote {out_html_path}")
    print(f"  assets: {len(uuid_to_relpath)} files in {os.path.join(out_dir, asset_subdir)}")
    print(f"  page_order entries (nested frames, unhandled if non-zero): {len(page_order)}")
    print(f"  ext_resources: {len(ext_resources)}")
    print(f"  UNRESOLVED uuid-looking strings left in output: {len(remaining_uuids)}")
    if remaining_uuids:
        print(f"    e.g. {remaining_uuids[:5]}")
    return out_html_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Usage: python tools_unpack_artifact_bundle.py "src.html" out_dir/')
        sys.exit(1)
    unpack(sys.argv[1], sys.argv[2])
