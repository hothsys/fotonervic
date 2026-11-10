#!/usr/bin/env python3
"""Build models/clipiqa_plus_rn50.onnx, the AI quality model used by Blur Check.

This is a one-off build step, not part of the app: the app only needs the
resulting .onnx file and onnxruntime. Run it in a throwaway virtual
environment, because it needs PyTorch (~2 GB):

    python3 -m venv /tmp/qm
    /tmp/qm/bin/pip install torch pyiqa onnx onnxscript onnxruntime "setuptools<80"
    /tmp/qm/bin/python tools/export_quality_model.py

What it builds: CLIP-IQA+ (Wang et al., "Exploring CLIP for Assessing the Look
and Feel of Images", AAAI 2023) as packaged by pyiqa: OpenAI CLIP's ResNet-50
image encoder plus two learned prompt embeddings ("good photo" / "bad photo")
trained on the KonIQ-10k dataset of human quality ratings. The text side never
changes, so the two prompt embeddings are computed once and baked in as
constants; the exported graph is image -> probability the photo is "good".

Licenses: the CLIP weights are MIT (OpenAI). The learned prompts come from
pyiqa (PolyForm Noncommercial 1.0.0), so the exported model is for
NON-COMMERCIAL use; see models/MODEL_LICENSE.md.
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, '..', 'models', 'clipiqa_plus_rn50.onnx')

# Fetched with curl into the cache paths pyiqa looks in, so pyiqa never tries
# its own downloaders (Hugging Face's CDN and Python's certificate store can
# both be blocked by corporate proxies, while curl uses the system trust store)
WEIGHTS = {
    'hub/clip/RN50.pt':
        'https://openaipublic.azureedge.net/clip/models/'
        'afeb0e10f9e5a86da6080e35cf09123aca3b358a0c3e3b6c78a7b63bc04b6762/RN50.pt',
    'hub/pyiqa/CLIP-IQA+_learned_prompts-603f3273.pth':
        'https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/'
        'CLIP-IQA+_learned_prompts-603f3273.pth',
}


def fetch_weights(torch_home):
    for rel, url in WEIGHTS.items():
        dest = os.path.join(torch_home, rel)
        if os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f'Downloading {os.path.basename(dest)} ...')
        subprocess.run(['curl', '-fL', '--retry', '3', '-o', dest + '.part', url], check=True)
        os.replace(dest + '.part', dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=DEFAULT_OUT, help='output .onnx path')
    args = ap.parse_args()

    torch_home = os.environ.setdefault('TORCH_HOME', os.path.join(tempfile.gettempdir(), 'fotonervic-torch'))
    fetch_weights(torch_home)

    import torch
    import torch.nn as nn
    import pyiqa

    metric = pyiqa.create_metric('clipiqa+', device='cpu')
    net = metric.net.eval()
    clip_model = net.clip_model[0].float().eval()
    with torch.no_grad():
        text = net.prompt_learner(clip_model)
        text = text / text.norm(dim=-1, keepdim=True)

    class CLIPIQAPlus(nn.Module):
        """(1, 3, H, W) RGB in [0, 1] -> (1, 1) probability the photo is 'good'."""

        def __init__(self):
            super().__init__()
            self.visual = clip_model.visual
            self.register_buffer('mean', net.default_mean.clone())
            self.register_buffer('std', net.default_std.clone())
            self.register_buffer('text', text.clone())
            self.scale = float(clip_model.logit_scale.exp())

        def forward(self, x):
            x = (x - self.mean) / self.std
            f = self.visual(x, return_token=False, pos_embedding=False)  # any image size
            f = f / f.norm(dim=-1, keepdim=True)
            return (self.scale * f @ self.text.t()).softmax(dim=-1)[:, 0:1]

    model = CLIPIQAPlus().eval()

    # The wrapper must reproduce pyiqa exactly before it's exported
    torch.manual_seed(0)
    probe = torch.rand(1, 3, 576, 768)
    with torch.no_grad():
        ref, ours = float(metric(probe)), float(model(probe))
    if abs(ref - ours) > 1e-4:
        sys.exit(f'Wrapper mismatch: pyiqa {ref:.6f} vs export {ours:.6f}')

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    torch.onnx.export(model, probe, out, input_names=['image'], output_names=['quality'],
                      dynamic_axes={'image': {2: 'height', 3: 'width'}},
                      opset_version=17, dynamo=False)

    import onnxruntime as ort
    got = float(ort.InferenceSession(out, providers=['CPUExecutionProvider'])
                .run(None, {'image': probe.numpy()})[0][0, 0])
    if abs(got - ref) > 1e-4:
        sys.exit(f'ONNX mismatch: pyiqa {ref:.6f} vs onnxruntime {got:.6f}')

    digest = hashlib.sha256(open(out, 'rb').read()).hexdigest()
    print(f'Wrote {out} ({os.path.getsize(out) / 1048576:.1f} MB)')
    print(f'SHA-256 {digest}')


if __name__ == '__main__':
    main()
