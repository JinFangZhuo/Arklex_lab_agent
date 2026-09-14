"""Download a pinned local model/runtime, optionally build CUDA, and serve on loopback."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def download(url, destination, expected_sha=None):
    if destination.exists() and (expected_sha is None or sha256(destination) == expected_sha):
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "LabBook-reproduction"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    if expected_sha and sha256(temporary) != expected_sha:
        raise RuntimeError(f"Download checksum mismatch: {destination.name}")
    temporary.replace(destination)


def extract(archive, directory):
    with tarfile.open(archive) as handle:
        handle.extractall(directory, filter="data")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["download", "build-cuda", "serve"])
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    parser.add_argument("--backend", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--port", type=int, default=18123)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--cuda-root", type=Path)
    parser.add_argument("--cuda-architecture", default="89", help="L40 uses compute capability 8.9")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "model_manifest.json").read_text())
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    if args.command == "download":
        archive = runtime / Path(manifest["llama_url"]).name
        download(manifest["llama_url"], archive, manifest["llama_sha256"])
        extract(archive, runtime)
        download(manifest["model_url"], runtime / manifest["model_filename"], manifest["model_sha256"])
        print("Pinned model and CPU runtime ready.")
    elif args.command == "build-cuda":
        archive = runtime / "llama-source-b10809.tar.gz"
        download(manifest["llama_source_url"], archive, manifest.get("llama_source_sha256"))
        extract(archive, runtime)
        command = ["cmake", "-S", str(runtime / "llama.cpp-b10809"), "-B", str(runtime / "llama-cuda-build"), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DGGML_CUDA=ON", f"-DCMAKE_CUDA_ARCHITECTURES={args.cuda_architecture}", "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DLLAMA_CURL=OFF"]
        if args.cuda_root:
            command.extend([f"-DCUDAToolkit_ROOT={args.cuda_root}", f"-DCMAKE_CUDA_COMPILER={args.cuda_root / 'bin/nvcc'}"])
        subprocess.run(command, check=True)
        subprocess.run(["cmake", "--build", str(runtime / "llama-cuda-build"), "--target", "llama-server", "-j", str(args.threads)], check=True)
    else:
        binary = runtime / ("llama-cuda-build/bin/llama-server" if args.backend == "cuda" else "llama-b10809/llama-server")
        if not binary.exists():
            parser.error("Runtime is missing: run download and, for CUDA, build-cuda first.")
        command = [str(binary), "--model", str(runtime / manifest["model_filename"]), "--alias", "qwen2.5-3b-instruct", "--host", "127.0.0.1", "--port", str(args.port), "--api-key", "local-model", "--threads", str(args.threads), "--threads-batch", str(args.threads), "--parallel", "1", "--ctx-size", str(args.context), "--no-webui"]
        if args.backend == "cuda":
            os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
            command.extend(["--n-gpu-layers", "99"])
        os.execv(binary, command)


if __name__ == "__main__":
    main()
